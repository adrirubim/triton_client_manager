"""
Simple WebSocket client for manual testing.

Protocol:
    - First message MUST be an "auth" message with fields:
        { "uuid": "<client-id>", "type": "auth", "payload": {...} }
    - Subsequent messages MUST reuse the same "uuid".
"""

import asyncio
import json
from typing import Any, Dict

from websockets.asyncio.client import connect


async def test_client() -> None:
    uri = "ws://127.0.0.1:8000/ws"
    client_uuid = "test-client-123"

    print("Starting WebSocket test client...")
    print(f"Connecting to: {uri}\n")

    try:
        async with connect(uri) as websocket:
            print("Connected to server.\n")

            # ========== STEP 1: Send Auth ==========
            print("=" * 60)
            print("[STEP 1] Sending authentication")
            print("=" * 60)

            auth_message: Dict[str, Any] = {
                "uuid": client_uuid,
                "type": "auth",
                "payload": {},
            }

            print("\nSending auth message:")
            print(json.dumps(auth_message, indent=2))

            await websocket.send(json.dumps(auth_message))
            print("Auth message sent.")

            # Wait for auth response
            auth_response = await websocket.recv()
            auth_data = json.loads(auth_response)

            print("\nReceived auth response:")
            print(json.dumps(auth_data, indent=2))

            if auth_data.get("type") != "auth.ok":
                print("\nAuthentication failed.")
                return

            print("\nAuthentication successful.")

            # ========== STEP 2: Send Info Request ==========
            print("\n" + "=" * 60)
            print("[STEP 2] Sending info request (queue_stats)")
            print("=" * 60)

            info_request: Dict[str, Any] = {
                "uuid": client_uuid,
                "type": "info",
                "payload": {
                    "action": "queue_stats",
                },
            }

            print("\nSending info request:")
            print(json.dumps(info_request, indent=2))

            await websocket.send(json.dumps(info_request))
            print("Info request sent.")

            # Wait for response
            print("\nWaiting for server response...")
            response = await websocket.recv()
            response_data = json.loads(response)

            print("\nReceived response:")
            print(json.dumps(response_data, indent=2))

            print("\nTest completed successfully.")

    except Exception as e:
        print(f"\nERROR: {e}")


if __name__ == "__main__":
    asyncio.run(test_client())
