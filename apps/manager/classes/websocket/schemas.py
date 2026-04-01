from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, Field


class BaseMessage(BaseModel):
    """Top-level WebSocket message envelope."""

    uuid: str = Field(..., description="Client identifier (top-level UUID)")
    type: Literal["auth", "info", "management", "inference"]
    payload: Dict[str, Any]


class AuthMessage(BaseMessage):
    type: Literal["auth"] = "auth"
    payload: Dict[str, Any] = Field(default_factory=dict)


class InfoPayload(BaseModel):
    action: Optional[str] = Field(
        default="queue_stats",
        description="`queue` or `queue_stats`",
    )


class InfoMessage(BaseMessage):
    type: Literal["info"] = "info"
    payload: InfoPayload


class ManagementPayload(BaseModel):
    action: str
    openstack: Dict[str, Any] = Field(default_factory=dict)
    docker: Dict[str, Any] = Field(default_factory=dict)
    minio: Dict[str, Any] = Field(default_factory=dict)
    triton: Dict[str, Any] = Field(default_factory=dict)


class ManagementMessage(BaseMessage):
    type: Literal["management"] = "management"
    payload: ManagementPayload


class InferenceInputsEntry(BaseModel):
    name: str
    type: str
    dims: Any
    value: Any


class SdkInferenceInputEntry(BaseModel):
    """
    SDK-friendly input shape accepted by some clients:
    - {name, shape, datatype, data}
    """

    name: str
    shape: list[int]
    datatype: str
    data: Any


class InferenceRequestConfig(BaseModel):
    protocol: Literal["http", "grpc"] = "http"


class InferencePayload(BaseModel):
    vm_id: str
    container_id: str
    model_name: str
    inputs: list[Union[InferenceInputsEntry, SdkInferenceInputEntry]]
    request: InferenceRequestConfig = Field(default_factory=InferenceRequestConfig)


class InferenceMessage(BaseMessage):
    type: Literal["inference"] = "inference"
    payload: InferencePayload
