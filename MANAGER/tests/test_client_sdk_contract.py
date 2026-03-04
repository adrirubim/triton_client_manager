"""
Tests de contrato para el SDK WebSocket (`_______WEBSOCKET.sdk`).

Objetivo: garantizar que el quickstart documentado funciona contra el servidor
de pruebas (`ws_server`) y que el contrato `auth` + `info.queue_stats` se
mantiene alineado con `docs/WEBSOCKET_API.md`.
"""

import pytest

from _______WEBSOCKET.sdk import AuthContext, TcmWebSocketClient, quickstart_queue_stats


@pytest.mark.asyncio
async def test_sdk_auth_and_info_queue_stats(ws_server):
    uri = ws_server

    ctx = AuthContext(
        uuid="sdk-test-client",
        token="dummy-token",
        sub="user-sdk-test",
        tenant_id="tenant-sdk-test",
        roles=["inference", "management"],
    )

    async with TcmWebSocketClient(uri, ctx) as client:
        auth_resp = await client.auth()
        assert auth_resp.get("type") == "auth.ok"

        info_resp = await client.info_queue_stats()
        assert info_resp.get("type") == "info_response"
        payload = info_resp.get("payload", {})
        assert payload.get("status") == "success"
        data = payload.get("data", {})
        assert "total_queued" in data
        assert "executor_info_available" in data


@pytest.mark.asyncio
async def test_quickstart_helper_matches_contract(ws_server):
    """
    Verifica que `quickstart_queue_stats` funciona como en el README del SDK.
    """

    result = await quickstart_queue_stats(ws_server)
    assert result.get("type") == "info_response"
    payload = result.get("payload", {})
    assert payload.get("status") == "success"
