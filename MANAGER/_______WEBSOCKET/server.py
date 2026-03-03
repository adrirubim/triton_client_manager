"""
Simple WebSocket Server Test
Shows exactly what format messages arrive in
"""

import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn


app = FastAPI()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("\n" + "="*60)
    print("CLIENT CONNECTED")
    print("="*60)
    
    client_id = None
    
    try:
        # ========== STEP 1: Receive Auth ==========
        print("\n[STEP 1] Waiting for auth message...")
        raw_auth = await websocket.receive_text()
        
        print(f"\n📥 RAW MESSAGE RECEIVED:")
        print(f"   Type: {type(raw_auth)}")
        print(f"   Content: {raw_auth}")
        
        auth_data = json.loads(raw_auth)
        print(f"\n📦 PARSED MESSAGE:")
        print(f"   Type: {type(auth_data)}")
        print(f"   Content: {json.dumps(auth_data, indent=2)}")
        
        # Extract user_id
        if auth_data.get("type") != "auth":
            print("\n❌ ERROR: Not an auth message!")
            await websocket.close()
            return
        
        client_id = auth_data.get("payload", {}).get("user_id")
        if not client_id:
            print("\n❌ ERROR: No user_id in auth payload!")
            await websocket.close()
            return
        
        print(f"\n✅ AUTH SUCCESS")
        print(f"   Client ID: {client_id}")
        
        # Send auth confirmation
        await websocket.send_text(json.dumps({"type": "auth.ok"}))
        
        
        # ========== STEP 2: Receive Regular Message ==========
        print("\n" + "-"*60)
        print("[STEP 2] Waiting for regular message...")
        
        raw_message = await websocket.receive_text()
        
        print(f"\n📥 RAW MESSAGE RECEIVED:")
        print(f"   Type: {type(raw_message)}")
        print(f"   Content: {raw_message}")
        
        message = json.loads(raw_message)
        print(f"\n📦 PARSED MESSAGE (before adding user_id):")
        print(f"   Type: {type(message)}")
        print(f"   Content: {json.dumps(message, indent=2)}")
        
        # Add user_id (this is what WebSocketThread does)
        message["user_id"] = client_id
        
        print(f"\n🎯 FINAL MESSAGE (what JobThread.on_event receives):")
        print(f"   Type: {type(message)}")
        print(f"   Content: {json.dumps(message, indent=2)}")
        
        print(f"\n📊 MESSAGE STRUCTURE:")
        print(f"   message['type'] = {message.get('type')}")
        print(f"   message['user_id'] = {message.get('user_id')}")
        print(f"   message['payload'] = {json.dumps(message.get('payload'), indent=2)}")
        
        # Send response
        response = {
            "type": "info_response",
            "payload": {
                "status": "success",
                "message": "Server received your request!",
                "you_sent": message
            }
        }
        await websocket.send_text(json.dumps(response))
        print(f"\n✅ Response sent to client")
        
        # Keep connection alive
        print(f"\n⏳ Keeping connection alive...")
        await asyncio.sleep(5)
        
    except WebSocketDisconnect:
        print(f"\n👋 Client {client_id} disconnected")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
    finally:
        print("\n" + "="*60)
        print("CONNECTION CLOSED")
        print("="*60 + "\n")


if __name__ == "__main__":
    print("🚀 Starting WebSocket Test Server...")
    print("📍 Listening on: ws://localhost:8000/ws")
    print("⏳ Waiting for connections...\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
