import asyncio
import json
import logging

import pytest

from classes.websocket.websocketthread import WebSocketThread


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

    # Client, pero sin loop
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
    ws.loop = object()  # marcador, no usamos un loop real

    def fake_run_coroutine_threadsafe(coro, loop):
        class _F:
            def result(self, timeout=None):
                asyncio.run(coro)

        return _F()

    monkeypatch.setattr(
        asyncio, "run_coroutine_threadsafe", fake_run_coroutine_threadsafe
    )

    assert ws.send_to_client("c1", {"x": 1}) is True
    assert dummy.sent
    sent_msg = json.loads(dummy.sent[0])
    assert sent_msg == {"x": 1}


@pytest.mark.asyncio
async def test_handle_client_rejects_oversized_and_invalid_messages(
    monkeypatch, caplog
):
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
    dummy2.accept = accept
    dummy2.receive_text = recv_text_bad_json

    await ws._handle_client(dummy2)
    assert hasattr(dummy2, "closed_code")
    assert dummy2.closed_code == 1008
