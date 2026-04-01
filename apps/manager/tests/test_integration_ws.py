"""
Integration tests for WebSocket server (auth, info, multi-client).
Requires: pytest, pytest-asyncio, websockets.
Run: cd apps/manager && pytest tests/test_integration_ws.py -v
"""

import json

import pytest
from websockets.client import connect


@pytest.mark.asyncio
async def test_auth_and_info(ws_server):
    """Auth and queue_stats info work over WebSocket."""
    uri = ws_server
    async with connect(uri) as sock:
        auth_msg = {
            "type": "auth",
            "uuid": "pytest-client",
            "payload": {
                # Minimal client block to exercise multi-tenant auth path
                "client": {
                    "sub": "user-test",
                    "tenant_id": "tenant-test",
                    "roles": ["inference", "management"],
                }
            },
        }
        await sock.send(json.dumps(auth_msg))
        r = json.loads(await sock.recv())
        assert r.get("type") == "auth.ok", r

        info_msg = {
            "type": "info",
            "uuid": "pytest-client",
            "payload": {"action": "queue_stats"},
        }
        await sock.send(json.dumps(info_msg))
        r = json.loads(await sock.recv())
        assert r.get("type") == "info_response", r
        assert r.get("payload", {}).get("status") == "success", r


@pytest.mark.asyncio
async def test_multiple_clients(ws_server):
    """Multiple clients can connect and exchange messages concurrently."""
    from devtools.ws_client import test_multiple_clients as run_multiple_clients

    await run_multiple_clients(uri=ws_server, keep_alive_sec=0.5)


async def _recv_json(sock):
    raw = await sock.recv()
    return json.loads(raw)


@pytest.mark.asyncio
async def test_ws_rejects_invalid_json(ws_server):
    """First message with invalid JSON returns an error."""
    uri = ws_server
    async with connect(uri) as sock:
        await sock.send("not-json")
        resp = await _recv_json(sock)
        assert resp["type"] == "error"
        assert resp["payload"]["message"] == "Invalid JSON format"


@pytest.mark.asyncio
async def test_ws_requires_auth_first(ws_server):
    """First message that is not auth returns an error."""
    uri = ws_server
    async with connect(uri) as sock:
        msg = {"type": "info", "uuid": "u1", "payload": {"action": "queue_stats"}}
        await sock.send(json.dumps(msg))
        resp = await _recv_json(sock)
        assert resp["type"] == "error"
        assert resp["payload"]["message"] == "First message must be type 'auth'"


@pytest.mark.asyncio
async def test_ws_invalid_type_and_uuid_mismatch(ws_server):
    """Validates unsupported types and UUID mismatch handling."""
    uri = ws_server
    async with connect(uri) as sock:
        # Successful auth
        auth = {"type": "auth", "uuid": "client-1", "payload": {}}
        await sock.send(json.dumps(auth))
        auth_ok = await _recv_json(sock)
        assert auth_ok["type"] == "auth.ok"

        # Unsupported message type
        bad_type = {"type": "unknown", "uuid": "client-1", "payload": {}}
        await sock.send(json.dumps(bad_type))
        err1 = await _recv_json(sock)
        assert err1["type"] == "error"
        assert "Invalid type" in err1["payload"]["message"]

        # UUID mismatch
        mismatch = {
            "type": "info",
            "uuid": "other",
            "payload": {"action": "queue_stats"},
        }
        await sock.send(json.dumps(mismatch))
        err2 = await _recv_json(sock)
        assert err2["type"] == "error"
        assert "UUID mismatch" in err2["payload"]["message"]
