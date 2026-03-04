"""
Test WebSocket client to connect to the WebSocketThread server.

Usage:
    python tests/ws_client_test.py
"""

import asyncio
import json

from websockets.asyncio.client import connect


async def test_client(
    user_id: str = "test-client",
    uri: str = "ws://localhost:8000/ws",
    keep_alive_sec: float = 10,
):
    """Test client that connects and sends requests"""

    try:
        async with connect(uri) as websocket:
            print(f"[{user_id}] Connected to server")

            # Send authentication (server expects top-level uuid as client_id)
            auth_msg = {"type": "auth", "uuid": user_id, "payload": {}}
            await websocket.send(json.dumps(auth_msg))
            print(f"[{user_id}] Sent auth")

            # Wait for auth response
            response = await websocket.recv()
            auth_response = json.loads(response)
            print(f"[{user_id}] Auth response: {auth_response}")

            if auth_response.get("type") != "auth.ok":
                print(f"[{user_id}] Auth failed!")
                return

            # Send info request for queue stats (uuid required at top level)
            info_request = {
                "type": "info",
                "uuid": user_id,
                "payload": {"action": "queue_stats"},
            }
            await websocket.send(json.dumps(info_request))
            print(f"[{user_id}] Sent info request")

            # Wait for response
            response = await websocket.recv()
            info_response = json.loads(response)
            print(f"[{user_id}] Info response:")
            print(json.dumps(info_response, indent=2))

            # Keep connection alive for a bit
            if keep_alive_sec > 0:
                print(f"[{user_id}] Keeping connection alive for {keep_alive_sec}s...")
                await asyncio.sleep(keep_alive_sec)

            print(f"[{user_id}] Closing connection")

    except Exception as e:
        print(f"[{user_id}] Error: {e}")


async def test_multiple_clients(
    uri: str = "ws://localhost:8000/ws", keep_alive_sec: float = 10
):
    """Test multiple clients connecting simultaneously"""
    tasks = [
        test_client("alice", uri=uri, keep_alive_sec=keep_alive_sec),
        test_client("bob", uri=uri, keep_alive_sec=keep_alive_sec),
        test_client("charlie", uri=uri, keep_alive_sec=keep_alive_sec),
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    print("Starting WebSocket client test...")
    print("Make sure the server is running first!")
    print("-" * 50)

    # Run single client test
    # asyncio.run(test_client("test_user"))

    # Run multiple clients test
    asyncio.run(test_multiple_clients())
