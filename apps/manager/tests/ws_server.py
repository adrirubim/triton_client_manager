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


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    print("Client connected")

    try:
        # Expect auth first
        raw = await ws.receive_text()
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_text(
                json.dumps({"type": "error", "payload": {"message": "Invalid JSON format"}})
            )
            await ws.close(code=1003)
            return

        if msg.get("type") != "auth":
            await ws.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "payload": {"message": "First message must be type 'auth'"},
                    }
                )
            )
            await ws.close(code=1008)
            return

        client_uuid = msg.get("uuid")
        if not client_uuid:
            await ws.send_text(
                json.dumps({"type": "error", "payload": {"message": "Missing uuid"}})
            )
            await ws.close(code=1008)
            return

        await ws.send_text(json.dumps({"type": "auth.ok"}))

        # Keep listening (optional)
        while True:
            raw = await ws.receive_text()
            print("RX:", raw)

            try:
                req = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(
                    json.dumps({"type": "error", "payload": {"message": "Invalid JSON format"}})
                )
                continue

            if req.get("uuid") != client_uuid:
                await ws.send_text(
                    json.dumps({"type": "error", "payload": {"message": "UUID mismatch"}})
                )
                continue

            req_type = req.get("type")

            if req_type == "info" and (req.get("payload") or {}).get("action") == "queue_stats":
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "info_response",
                            "payload": {
                                "status": "success",
                                "request_type": "queue_stats",
                                "data": {
                                    "info_users": 0,
                                    "management_users": 0,
                                    "inference_users": 0,
                                    "total_users": 0,
                                    "total_queued": 0,
                                    "info_total_queued": 0,
                                    "management_total_queued": 0,
                                    "inference_total_queued": 0,
                                    "executor_info_pending": 0,
                                    "executor_management_pending": 0,
                                    "executor_inference_pending": 0,
                                    "executor_info_available": 0,
                                    "executor_management_available": 0,
                                    "executor_inference_available": 0,
                                },
                            },
                        }
                    )
                )
                continue

            if req_type == "unknown":
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "payload": {
                                "message": "Invalid type 'unknown'. Must be one of: ['auth', 'info', 'management', 'inference']"
                            },
                        }
                    )
                )
                continue

            await ws.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "payload": {"message": f"Invalid type {req_type!r}."},
                    }
                )
            )

    except WebSocketDisconnect:
        print("Client disconnected")
