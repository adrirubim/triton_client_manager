from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import Body, FastAPI, HTTPException

from tcm_client.sdk import AuthContext, InferenceInput, TcmClient

JsonDict = Dict[str, Any]

app = FastAPI(title="TCM FastAPI Inference Proxy")


def _build_auth_context() -> AuthContext:
    """
    Small helper to construct the AuthContext from environment variables.
    """

    uuid = os.getenv("TCM_CLIENT_UUID", "fastapi-proxy")
    token = os.getenv("TCM_CLIENT_TOKEN", "dummy-token")
    sub = os.getenv("TCM_CLIENT_SUB", uuid)
    tenant_id = os.getenv("TCM_CLIENT_TENANT_ID", "tenant-sdk")
    roles = os.getenv("TCM_CLIENT_ROLES", "inference,management").split(",")

    return AuthContext(
        uuid=uuid,
        token=token,
        sub=sub,
        tenant_id=tenant_id,
        roles=[role.strip() for role in roles if role.strip()],
    )


def _build_client() -> TcmClient:
    uri = os.getenv("TCM_WS_URI", "ws://127.0.0.1:8000/ws")
    return TcmClient(uri=uri, auth_ctx=_build_auth_context())


@app.post("/infer/{vm_id}/{container_id}/{model_name}")
def infer(
    vm_id: str,
    container_id: str,
    model_name: str,
    inputs: List[JsonDict] = Body(..., description="Lista de tensores Triton"),
) -> JsonDict:
    """
    Proxy HTTP -> WebSocket usando el SDK.
    """
    client = _build_client()
    try:
        typed_inputs = [InferenceInput(**item) for item in inputs]
        response = client.infer(
            vm_id=vm_id,
            container_id=container_id,
            model_name=model_name,
            inputs=typed_inputs,
        )
    except Exception as exc:  # pragma: no cover - ejemplo simple
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "type": response.type,
        "payload": response.payload,
    }
