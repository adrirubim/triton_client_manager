"""
Contract tests for the Python WebSocket SDK used against the local ws_server.

These tests ensure that the examples in sdk/README.md and
MANAGER/_______WEBSOCKET/README.md remain valid against the actual server
implementation and the contract documented in docs/WEBSOCKET_API.md.
"""

import pytest

from _______WEBSOCKET.sdk import (
    AuthContext,
    TcmWebSocketClient,
    quickstart_queue_stats,
)


def _make_auth_ctx() -> AuthContext:
    """
    Build an AuthContext that exercises the multi-tenant auth path.
    """

    return AuthContext(
        uuid="sdk-contract-client",
        token="dummy-token",
        sub="sdk-user",
        tenant_id="sdk-tenant",
        roles=["inference", "management"],
    )


@pytest.mark.asyncio
async def test_auth_flow_ok(ws_server):
    """
    Test 1: auth() flow -> Verify `auth.ok` response.
    """

    auth_ctx = _make_auth_ctx()

    async with TcmWebSocketClient(ws_server, auth_ctx) as client:
        resp = await client.auth()

    assert resp.get("type") == "auth.ok", resp


@pytest.mark.asyncio
async def test_info_queue_stats_contract(ws_server):
    """
    Test 2: info_queue_stats() -> Verify JSON structure matches docs/WEBSOCKET_API.md.
    """

    auth_ctx = _make_auth_ctx()

    async with TcmWebSocketClient(ws_server, auth_ctx) as client:
        # First, perform auth as required by the protocol.
        auth_resp = await client.auth()
        assert auth_resp.get("type") == "auth.ok", auth_resp

        # Then request queue stats via the SDK helper.
        resp = await client.info_queue_stats()

    assert resp.get("type") == "info_response", resp

    payload = resp.get("payload") or {}
    # Shape-level assertions, aligned with docs/WEBSOCKET_API.md
    assert payload.get("status") == "success", payload
    assert payload.get("request_type") == "queue_stats", payload
    assert "data" in payload, payload

    data = payload["data"]
    # The exact numbers may vary, but the keys must be present.
    expected_keys = {
        "info_users",
        "management_users",
        "inference_users",
        "total_users",
        "total_queued",
        "info_total_queued",
        "management_total_queued",
        "inference_total_queued",
        "executor_info_pending",
        "executor_management_pending",
        "executor_inference_pending",
        "executor_info_available",
        "executor_management_available",
        "executor_inference_available",
    }
    missing = expected_keys.difference(data.keys())
    assert not missing, f"Missing keys in info.queue_stats data: {missing}"


@pytest.mark.asyncio
async def test_error_contract_for_invalid_type(ws_server):
    """
    Test 3: Error handling -> Send an invalid payload and assert error type matches docs.
    """

    auth_ctx = _make_auth_ctx()

    async with TcmWebSocketClient(ws_server, auth_ctx) as client:
        # Successful auth to establish the session.
        auth_resp = await client.auth()
        assert auth_resp.get("type") == "auth.ok", auth_resp

        # Use the low-level `_send` helper to craft an invalid message type.
        invalid_msg = {
            "uuid": auth_ctx.uuid,
            "type": "unknown",
            "payload": {},
        }
        resp = await client._send(invalid_msg)  # type: ignore[attr-defined]

    assert resp.get("type") == "error", resp
    message = (resp.get("payload") or {}).get("message", "")
    # Contract from docs/WEBSOCKET_API.md → "Invalid type 'unknown'. Must be one of: [...]"
    assert "Invalid type 'unknown'" in message, message


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
