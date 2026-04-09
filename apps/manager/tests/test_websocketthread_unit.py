import asyncio
import json
import logging
import time

import pytest
from fastapi import WebSocketDisconnect

from classes.websocket.websocketthread import WebSocketThread


@pytest.fixture(autouse=True)
def _force_development_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests in this module rely on development-mode auth behavior (claims-only strict mode).
    monkeypatch.setenv("TCM_ENV", "development")


def _make_jwt(payload: dict) -> str:
    """
    Minimal unsigned JWT for dev-mode strict tests.
    utils.auth falls back to claims-only decode in development when no key material is configured.
    """
    import base64

    header = {"alg": "none", "typ": "JWT"}

    def enc(obj: dict) -> bytes:
        return json.dumps(obj, separators=(",", ":")).encode("utf-8")

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

    return ".".join([b64url(enc(header)), b64url(enc(payload)), ""])


class _DummyWebSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text: str):
        self.sent.append(text)

    async def close(self, code: int | None = None):
        self.closed_code = code


def test_validate_message_variants():
    ws = WebSocketThread(
        host="127.0.0.1",
        port=0,
        valid_types=["info"],
        on_message=lambda *_args, **_kwargs: None,
    )

    ok, err = ws._validate_message({"uuid": "u", "type": "info", "payload": {}})
    assert ok is True
    assert err == ""

    ok, err = ws._validate_message({})
    assert ok is False and "Missing required field" in err

    ok, err = ws._validate_message({"uuid": 123, "type": "info", "payload": {}})
    assert ok is False and "must be a string" in err

    ok, err = ws._validate_message({"uuid": "u", "type": "bad", "payload": {}})
    assert ok is False and "Invalid type" in err


def test_send_to_client_no_client_or_loop(monkeypatch):
    ws = WebSocketThread(
        host="127.0.0.1",
        port=0,
        valid_types=["info"],
        on_message=lambda *_args, **_kwargs: None,
    )

    # No client registered
    assert ws.send_to_client("missing", {"x": 1}) is False

    # Client registered, but no event loop set
    ws.clients["c1"] = _DummyWebSocket()
    assert ws.send_to_client("c1", {"x": 1}) is False


def test_send_to_client_success(monkeypatch):
    ws = WebSocketThread(
        host="127.0.0.1",
        port=0,
        valid_types=["info"],
        on_message=lambda *_args, **_kwargs: None,
    )
    dummy = _DummyWebSocket()
    ws.clients["c1"] = dummy
    ws.loop = object()  # marker; we don't use a real loop

    def fake_run_coroutine_threadsafe(coro, loop):
        # send_to_client is fire-and-forget; simulate immediate completion.
        asyncio.run(coro)

        class _F:
            def add_done_callback(self, cb):
                cb(self)

            def result(self, timeout=None):
                return None

        return _F()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", fake_run_coroutine_threadsafe)

    assert ws.send_to_client("c1", {"x": 1}) is True
    assert dummy.sent
    sent_msg = json.loads(dummy.sent[0])
    assert sent_msg == {"x": 1}


@pytest.mark.asyncio
async def test_handle_client_rejects_oversized_and_invalid_messages(monkeypatch, caplog):
    ws = WebSocketThread(
        host="127.0.0.1",
        port=0,
        valid_types=["auth", "info"],
        on_message=lambda *_args, **_kwargs: None,
    )
    ws.max_message_bytes = 1  # make any non-empty JSON be "too large"

    dummy = _DummyWebSocket()

    async def accept():
        return None

    # First, test oversized message path
    async def recv_text_too_big():
        return json.dumps({"uuid": "u", "type": "auth", "payload": {}})

    dummy.accept = accept
    dummy.receive_text = recv_text_too_big

    with caplog.at_level(logging.INFO):
        await ws._handle_client(dummy)

    assert hasattr(dummy, "closed_code")
    assert dummy.closed_code == 1009

    # Now test invalid JSON path
    ws.max_message_bytes = 64 * 1024

    async def recv_text_bad_json():
        return "not-json"

    dummy2 = _DummyWebSocket()
    dummy2.accept = accept  # type: ignore[attr-defined]
    dummy2.receive_text = recv_text_bad_json  # type: ignore[attr-defined]

    await ws._handle_client(dummy2)
    assert hasattr(dummy2, "closed_code")
    assert dummy2.closed_code == 1008


@pytest.mark.asyncio
async def test_rate_limit_state_is_cleared_on_disconnect() -> None:
    ws = WebSocketThread(
        host="127.0.0.1",
        port=0,
        valid_types=["auth", "info"],
        on_message=lambda *_args, **_kwargs: None,
    )

    client_id = "u-cleanup-1"
    # Pre-populate rate-limit state to ensure it is cleared in finally.
    ws._msg_timestamps[client_id] = [time.time()]  # type: ignore[name-defined]
    ws._auth_fail_timestamps[client_id] = [time.time()]  # type: ignore[name-defined]

    dummy = _DummyWebSocket()
    calls = 0

    async def accept():
        return None

    async def recv_text():
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps({"uuid": client_id, "type": "auth", "payload": {"token": None}})
        raise WebSocketDisconnect()

    dummy.accept = accept  # type: ignore[attr-defined]
    dummy.receive_text = recv_text  # type: ignore[attr-defined]

    await ws._handle_client(dummy)

    assert client_id not in ws._msg_timestamps
    # Auth-failure timestamps are intentionally retained to rate limit reconnect attempts.

    dummy2 = _DummyWebSocket()
    dummy2.accept = accept

    # Invalid JSON should be rejected and close in auth phase.
    async def recv_text_bad_json():
        return "not-json"

    dummy2.receive_text = recv_text_bad_json  # type: ignore[attr-defined]

    await ws._handle_client(dummy2)
    assert hasattr(dummy2, "closed_code")
    assert dummy2.closed_code == 1008


@pytest.mark.asyncio
async def test_handle_client_rejects_invalid_auth_payload(monkeypatch):
    ws = WebSocketThread(
        host="127.0.0.1",
        port=0,
        valid_types=["auth", "info"],
        on_message=lambda *_args, **_kwargs: None,
    )

    dummy = _DummyWebSocket()

    async def accept():
        return None

    calls = 0

    # auth message with malformed client block.
    # Client-provided identity/roles are ignored; token drives auth context in strict mode.
    async def recv_text_bad_auth():
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps(
                {
                    "uuid": "u",
                    "type": "auth",
                    "payload": {
                        "token": _make_jwt(
                            {
                                "sub": "user-1",
                                "roles": ["inference"],
                                "exp": int(time.time()) + 60,
                            }
                        ),
                        "client": {"sub": 123, "tenant_id": None, "roles": "x"},
                    },
                }
            )
        raise WebSocketDisconnect()

    dummy.accept = accept
    dummy.receive_text = recv_text_bad_auth  # type: ignore[attr-defined]

    ws.set_auth_and_rate_limits(
        auth_config={"mode": "strict", "require_token": True},
        rate_limit_config=None,
    )

    await ws._handle_client(dummy)
    # Should authenticate successfully and ignore malformed client block.
    assert dummy.sent
    assert json.loads(dummy.sent[0]) == {"type": "auth.ok"}


@pytest.mark.asyncio
async def test_roles_are_derived_from_jwt_claims_not_client_payload(monkeypatch):
    ws = WebSocketThread(
        host="127.0.0.1",
        port=0,
        valid_types=["auth", "info", "management", "inference"],
        on_message=lambda *_args, **_kwargs: None,
    )
    ws.set_auth_and_rate_limits(
        auth_config={
            "mode": "strict",
            "require_token": True,
            "required_claims": ["sub"],
        },
        rate_limit_config=None,
    )

    client_id = "u-roles-1"
    token = _make_jwt({"sub": "user-1", "roles": ["inference"], "exp": int(time.time()) + 60})

    dummy = _DummyWebSocket()

    async def accept():
        return None

    calls = 0

    async def recv_text():
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps(
                {
                    "uuid": client_id,
                    "type": "auth",
                    "payload": {
                        "token": token,
                        "client": {
                            "sub": "attacker",
                            "tenant_id": "t",
                            "roles": ["admin"],
                        },
                    },
                }
            )
        if calls == 2:
            # Assert before disconnect cleanup runs in finally.
            auth_ctx = ws.client_auth.get(client_id) or {}
            assert auth_ctx.get("sub") == "user-1"
            assert auth_ctx.get("roles") == ["inference"]
        raise WebSocketDisconnect()

    dummy.accept = accept  # type: ignore[attr-defined]
    dummy.receive_text = recv_text  # type: ignore[attr-defined]

    await ws._handle_client(dummy)
    # Auth context is cleared on disconnect; assertions are done on the second receive above.


@pytest.mark.asyncio
async def test_handle_client_rejects_invalid_token_in_strict_mode():
    ws = WebSocketThread(
        host="127.0.0.1",
        port=0,
        valid_types=["auth", "info"],
        on_message=lambda *_args, **_kwargs: None,
    )
    ws.set_auth_and_rate_limits(
        auth_config={"mode": "strict", "require_token": True},
        rate_limit_config=None,
    )

    dummy = _DummyWebSocket()

    async def accept():
        return None

    # auth message without token -> should be rejected in strict mode
    async def recv_text_no_token():
        return json.dumps(
            {
                "uuid": "u",
                "type": "auth",
                "payload": {
                    "client": {
                        "sub": "user",
                        "tenant_id": "tenant",
                        "roles": ["inference"],
                    }
                },
            }
        )

    dummy.accept = accept
    dummy.receive_text = recv_text_no_token

    await ws._handle_client(dummy)
    assert hasattr(dummy, "closed_code")
    assert dummy.closed_code == 1008
    # Last sent error should mention invalid token
    assert dummy.sent
    last_error = json.loads(dummy.sent[-1])
    assert last_error["type"] == "error"
    assert "Invalid token" in last_error["payload"]["message"]


def test_message_rate_limiter_basic():
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

    client_id = "c1"
    # First message should be allowed
    assert ws._check_message_rate(client_id) is True
    # Second message within the same second should be rejected
    assert ws._check_message_rate(client_id) is False
