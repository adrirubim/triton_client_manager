import json
import time

import jwt
import pytest

from classes.websocket.websocketthread import WebSocketThread
from utils.auth import validate_token
from utils.metrics import AUTH_FAILURES_TOTAL, RATE_LIMIT_VIOLATIONS_TOTAL


@pytest.fixture(autouse=True)
def _force_development_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # These tests rely on development-mode auth behavior (e.g. HS* algorithms and claims-only fallback).
    monkeypatch.setenv("TCM_ENV", "development")


def _counter_value(counter, **labels) -> float:
    """Helper to read the current value of a labeled Counter."""
    return counter.labels(**labels)._value.get()  # type: ignore[attr-defined]


def test_rate_limit_messages_increments_metric() -> None:
    """
    Explicitly exercise message rate limiting and verify that
    `tcm_rate_limit_violations_total{scope="messages"}` increments when the
    configured limit is exceeded.
    """
    ws = WebSocketThread(
        host="127.0.0.1",
        port=0,
        valid_types=["info"],
        on_message=lambda *_args, **_kwargs: None,
    )
    ws.set_auth_and_rate_limits(
        auth_config=None,
        rate_limit_config={"messages_per_second_per_client": 1},
    )

    client_id = "rate-limit-client"

    # First call within the window -> allowed, no metric.
    assert ws._check_message_rate(client_id) is True

    before = _counter_value(RATE_LIMIT_VIOLATIONS_TOTAL, scope="messages")

    # Second call within the same second -> rejected and metric +1.
    assert ws._check_message_rate(client_id) is False
    after = _counter_value(RATE_LIMIT_VIOLATIONS_TOTAL, scope="messages")

    assert after == before + 1


def test_validate_token_strict_with_invalid_signature_auth_fail_reason() -> None:
    """
    In strict mode, validate_token with `public_key_pem`/HS256 rejects tokens
    signed with a different secret and returns a coherent error message.
    """
    # Token signed with an "incorrect" secret (>= 32 bytes to avoid InsecureKeyLengthWarning).
    wrong_secret = "wrong-secret-for-hs256-test-32-bytes"
    payload = {
        "sub": "user-1",
        "aud": "tcm",
        "iss": "https://idp.example.com/",
        "exp": int(time.time()) + 300,
    }
    token = jwt.encode(payload, wrong_secret, algorithm="HS256")

    auth_cfg = {
        "mode": "strict",
        "require_token": True,
        "required_claims": ["exp", "aud", "iss"],
        "issuer": "https://idp.example.com/",
        "audience": "tcm",
        # This secret is expected; using another to sign makes the signature invalid.
        "public_key_pem": "expected-secret-for-hs256-32-bytes!!",
        "algorithms": ["HS256"],
    }

    ok, error = validate_token(token, auth_cfg)
    assert ok is False
    assert error  # Non-empty message


class _DummyWebSocket:
    def __init__(self):
        self.sent: list[str] = []
        self.closed_code: int | None = None

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int | None = None) -> None:
        self.closed_code = code


@pytest.mark.asyncio
async def test_auth_failures_in_strict_mode_increment_counters() -> None:
    """
    Invalid `auth` flows in strict mode:
    - Incrementan `tcm_auth_failures_total{reason="token"}`.
    - Respect the `auth_failures_per_minute_per_client` limit and, when exceeded,
      increment `tcm_rate_limit_violations_total{scope="auth"}` and close the connection.
    """
    ws = WebSocketThread(
        host="127.0.0.1",
        port=0,
        valid_types=["auth", "info"],
        on_message=lambda *_args, **_kwargs: None,
    )

    # Strict configuration with HS256 cryptographic validation (expected secret),
    # but the token is signed with a different secret to force a signature failure.
    auth_cfg = {
        "mode": "strict",
        "require_token": True,
        "required_claims": ["exp", "aud", "iss"],
        "issuer": "https://idp.example.com/",
        "audience": "tcm",
        "public_key_pem": "expected-secret-for-hs256-32-bytes!!",
        "algorithms": ["HS256"],
    }
    ws.set_auth_and_rate_limits(
        auth_config=auth_cfg,
        rate_limit_config={"auth_failures_per_minute_per_client": 1},
    )

    wrong_secret = "wrong-secret-for-hs256-test-32-bytes"
    payload = {
        "sub": "user-1",
        "aud": "tcm",
        "iss": "https://idp.example.com/",
        "exp": int(time.time()) + 300,
    }
    token = jwt.encode(payload, wrong_secret, algorithm="HS256")

    async def _make_dummy_ws():
        dummy = _DummyWebSocket()

        async def accept():
            return None

        async def recv_text():
            return json.dumps(
                {
                    "uuid": "client-token-test",
                    "type": "auth",
                    "payload": {
                        "token": token,
                        "client": {
                            "sub": "user-1",
                            "tenant_id": "tenant-1",
                            "roles": ["inference"],
                        },
                    },
                }
            )

        dummy.accept = accept  # type: ignore[attr-defined]
        dummy.receive_text = recv_text  # type: ignore[attr-defined]
        return dummy

    # First attempt: token failure, without exceeding the per-minute failure limit.
    before_auth = _counter_value(AUTH_FAILURES_TOTAL, reason="token")
    before_rl = _counter_value(RATE_LIMIT_VIOLATIONS_TOTAL, scope="auth")

    ws1 = await _make_dummy_ws()
    await ws._handle_client(ws1)

    mid_auth = _counter_value(AUTH_FAILURES_TOTAL, reason="token")
    mid_rl = _counter_value(RATE_LIMIT_VIOLATIONS_TOTAL, scope="auth")

    assert mid_auth == before_auth + 1
    assert mid_rl == before_rl
    assert ws1.closed_code == 1008
    assert ws1.sent
    last_error_1 = json.loads(ws1.sent[-1])
    assert last_error_1["type"] == "error"
    assert "Invalid token" in last_error_1["payload"]["message"]

    # Second attempt in the same window: another failure + auth rate limit trip.
    ws2 = await _make_dummy_ws()
    await ws._handle_client(ws2)

    after_auth = _counter_value(AUTH_FAILURES_TOTAL, reason="token")
    after_rl = _counter_value(RATE_LIMIT_VIOLATIONS_TOTAL, scope="auth")

    assert after_auth == mid_auth + 1
    assert after_rl == mid_rl + 1
    assert ws2.closed_code == 1008
    assert ws2.sent
    last_error_2 = json.loads(ws2.sent[-1])
    assert last_error_2["type"] == "error"
    assert "Too many failed auth attempts for this client" in last_error_2["payload"]["message"]
