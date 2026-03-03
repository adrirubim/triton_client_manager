"""
Integration tests for WebSocket server (auth, info, multi-client).
Requires: pytest, pytest-asyncio, websockets.
Run: cd MANAGER && pytest tests/test_integration_ws.py -v
"""

import json

from websockets.asyncio.client import connect


async def test_auth_and_info(ws_server):
    """Auth and queue_stats info work over WebSocket."""
    uri = ws_server
    async with connect(uri) as sock:
        auth_msg = {"type": "auth", "uuid": "pytest-client", "payload": {}}
        await sock.send(json.dumps(auth_msg))
        r = json.loads(await sock.recv())
        assert r.get("type") == "auth.ok", r

        info_msg = {"type": "info", "uuid": "pytest-client", "payload": {"action": "queue_stats"}}
        await sock.send(json.dumps(info_msg))
        r = json.loads(await sock.recv())
        assert r.get("type") == "info_response", r
        assert r.get("payload", {}).get("status") == "success", r


async def test_multiple_clients(ws_server):
    """Multiple clients can connect and exchange messages concurrently."""
    from ws_client_test import test_multiple_clients as run_multiple_clients

    await run_multiple_clients(uri=ws_server, keep_alive_sec=0.5)
