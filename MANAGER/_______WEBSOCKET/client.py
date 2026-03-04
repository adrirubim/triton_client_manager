"""
Simple WebSocket Client Test
Connects to server and sends test messages
"""

import asyncio
import json

from websockets.asyncio.client import connect


async def test_client():
    uri = "ws://localhost:8000/ws"

    print("🚀 Starting WebSocket Test Client...")
    print(f"📍 Connecting to: {uri}\n")

    try:
        async with connect(uri) as websocket:
            print("✅ Connected to server!\n")

            # ========== STEP 1: Send Auth ==========
            print("=" * 60)
            print("[STEP 1] Sending authentication...")
            print("=" * 60)

            auth_message = {"type": "auth", "payload": {"user_id": "test_user_123"}}

            print("\n📤 SENDING AUTH MESSAGE:")
            print(f"   Content: {json.dumps(auth_message, indent=2)}")

            await websocket.send(json.dumps(auth_message))
            print("   ✅ Sent!")

            # Wait for auth response
            auth_response = await websocket.recv()
            auth_data = json.loads(auth_response)

            print("\n📥 RECEIVED AUTH RESPONSE:")
            print(f"   Content: {json.dumps(auth_data, indent=2)}")

            if auth_data.get("type") != "auth.ok":
                print("\n❌ Authentication failed!")
                return

            print("\n✅ Authentication successful!")

            # ========== STEP 2: Send Info Request ==========
            print("\n" + "=" * 60)
            print("[STEP 2] Sending info request...")
            print("=" * 60)

            info_request = {
                "type": "info",
                "payload": {"job_id": "test-job-456", "request_type": "queue_stats"},
            }

            print("\n📤 SENDING INFO REQUEST:")
            print(f"   Content: {json.dumps(info_request, indent=2)}")
            print("\n   NOTE: user_id is NOT included here!")
            print("   The server will add it automatically.")

            await websocket.send(json.dumps(info_request))
            print("\n   ✅ Sent!")

            # Wait for response
            print("\n⏳ Waiting for server response...")
            response = await websocket.recv()
            response_data = json.loads(response)

            print("\n📥 RECEIVED RESPONSE:")
            print(f"   Content: {json.dumps(response_data, indent=2)}")

            # ========== Summary ==========
            print("\n" + "=" * 60)
            print("SUMMARY")
            print("=" * 60)
            print("\n✅ Test completed successfully!")
            print("\n📊 What the server received:")
            print(f"   - Original message: {json.dumps(info_request, indent=6)}")
            print(
                f"   - After adding user_id: {json.dumps(response_data['payload']['you_sent'], indent=6)}"
            )
            print(
                "\n🎯 Key point: Server automatically adds 'user_id' to every message!"
            )

            print("\n👋 Closing connection...")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("WebSocket Client Test")
    print("=" * 60 + "\n")

    asyncio.run(test_client())

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60 + "\n")
