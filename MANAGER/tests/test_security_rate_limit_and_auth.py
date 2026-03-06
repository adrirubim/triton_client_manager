import json
import time

import jwt
import pytest

from classes.websocket.websocketthread import WebSocketThread
from utils.auth import validate_token
from utils.metrics import AUTH_FAILURES_TOTAL, RATE_LIMIT_VIOLATIONS_TOTAL


def _counter_value(counter, **labels) -> float:
    """Helper to read the current value of a labeled Counter."""
    return counter.labels(**labels)._value.get()  # type: ignore[attr-defined]


def test_rate_limit_messages_increments_metric() -> None:
    """
    Exercita explícitamente el rate limiting por mensaje y verifica que
    `tcm_rate_limit_violations_total{scope="messages"}` se incrementa cuando
    se supera el límite configurado.
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

    # Primera llamada dentro de la ventana -> permitida, sin métrica.
    assert ws._check_message_rate(client_id) is True

    before = _counter_value(RATE_LIMIT_VIOLATIONS_TOTAL, scope="messages")

    # Segunda llamada dentro del mismo segundo -> rechazada y métrica +1.
    assert ws._check_message_rate(client_id) is False
    after = _counter_value(RATE_LIMIT_VIOLATIONS_TOTAL, scope="messages")

    assert after == before + 1


def test_validate_token_strict_with_invalid_signature_auth_fail_reason() -> None:
    """
    validate_token en modo strict con `public_key_pem`/HS256 rechaza tokens
    firmados con un secreto distinto y devuelve un mensaje coherente.
    """
    # Token firmado con un secreto "incorrecto"
    wrong_secret = "wrong-secret"
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
        # Se espera este secreto; al usar otro para firmar, la firma será inválida.
        "public_key_pem": "expected-secret",
        "algorithms": ["HS256"],
    }

    ok, error = validate_token(token, auth_cfg)
    assert ok is False
    assert error  # Mensaje no vacío


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
    Flujos de `auth` inválida en modo strict:
    - Incrementan `tcm_auth_failures_total{reason="token"}`.
    - Respetan el límite `auth_failures_per_minute_per_client` y, al superarlo,
      incrementan `tcm_rate_limit_violations_total{scope="auth"}` y cierran la conexión.
    """
    ws = WebSocketThread(
        host="127.0.0.1",
        port=0,
        valid_types=["auth", "info"],
        on_message=lambda *_args, **_kwargs: None,
    )

    # Configuración strict con validación criptográfica HS256 (secreto esperado),
    # pero el token se firma con otro secreto para provocar fallo de firma.
    auth_cfg = {
        "mode": "strict",
        "require_token": True,
        "required_claims": ["exp", "aud", "iss"],
        "issuer": "https://idp.example.com/",
        "audience": "tcm",
        "public_key_pem": "expected-secret",
        "algorithms": ["HS256"],
    }
    ws.set_auth_and_rate_limits(
        auth_config=auth_cfg,
        rate_limit_config={"auth_failures_per_minute_per_client": 1},
    )

    wrong_secret = "wrong-secret"
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

    # Primer intento: fallo de token, pero sin exceder el límite de fallos por minuto.
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

    # Segundo intento en la misma ventana: otro fallo + disparo del rate limit de auth.
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
    assert "Too many failed auth attempts for this client" in last_error_2["payload"][
        "message"
    ]

