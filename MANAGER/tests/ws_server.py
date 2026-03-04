import asyncio
import json
import uuid
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()


def build_hf_conversion_job_payload() -> Dict[str, Any]:
    return {
        "job_id": str(uuid.uuid4()),
        "job_type": "inference",
        "model_repo": "meta-llama/Llama-2-7b-hf",
        "source_format": "safetensors",
        "target_format": "gguf",
        "quant": "q4_k_m",
        "output_bucket": "models",
        "priority": "normal",
    }


async def send_job_loop(ws: WebSocket, interval_s: float = 5.0):
    """
    Sends a new job every `interval_s` seconds until cancelled/disconnected.
    """
    while True:
        payload = build_hf_conversion_job_payload()
        await ws.send_text(json.dumps({"type": "job", "payload": payload}))
        await asyncio.sleep(interval_s)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    print("Client connected")

    sender_task: asyncio.Task | None = None

    try:
        # Expect auth first
        raw = await ws.receive_text()
        msg = json.loads(raw)

        if msg.get("type") != "auth":
            await ws.send_text(
                json.dumps({"type": "error", "payload": {"message": "auth required"}})
            )
            await ws.close(code=1008)
            return

        await ws.send_text(json.dumps({"type": "auth.ok"}))

        # Start periodic job sender
        sender_task = asyncio.create_task(send_job_loop(ws, interval_s=5.0))

        # Keep listening (optional)
        while True:
            raw = await ws.receive_text()
            print("RX:", raw)

            # optional echo
            await ws.send_text(json.dumps({"type": "echo", "payload": json.loads(raw)}))

    except WebSocketDisconnect:
        print("Client disconnected")

    finally:
        if sender_task:
            sender_task.cancel()
            try:
                await sender_task
            except asyncio.CancelledError:
                pass
