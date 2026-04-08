from __future__ import annotations

from typing import List, Optional

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, PositiveInt


class JobsConfig(BaseModel):
    """Typed schema for `jobs.yaml`."""

    max_queue_size_info_per_user: PositiveInt
    max_queue_size_management_per_user: PositiveInt
    max_queue_size_inference_per_user: PositiveInt

    max_workers_info: PositiveInt
    max_workers_management: PositiveInt
    max_workers_inference: PositiveInt

    max_executor_queue_info: PositiveInt
    max_executor_queue_management: PositiveInt
    max_executor_queue_inference: PositiveInt

    queue_cleanup_interval: PositiveInt
    queue_idle_threshold: PositiveInt

    info_actions_available: List[str]
    management_actions_available: List[str]

    model_config = ConfigDict(extra="forbid")


class WebsocketAuthConfig(BaseModel):
    """`auth` subsection of `websocket.yaml`."""

    mode: str = Field(default="strict")
    require_token: bool = Field(default=True)
    required_claims: List[str] = Field(default_factory=list)
    issuer: Optional[str] = None
    audience: Optional[str] = None
    leeway_seconds: int = 60
    jwks_url: Optional[AnyHttpUrl] = None
    public_key_pem: Optional[str] = None
    algorithms: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class WebsocketRateLimitsConfig(BaseModel):
    """`rate_limits` subsection of `websocket.yaml`."""

    messages_per_second_per_client: int = 0
    auth_failures_per_minute_per_client: int = 0

    model_config = ConfigDict(extra="forbid")


class WebsocketConfig(BaseModel):
    """Typed schema for `websocket.yaml`."""

    host: str
    port: PositiveInt
    valid_types: List[str]
    max_message_bytes: PositiveInt
    auth: WebsocketAuthConfig
    rate_limits: WebsocketRateLimitsConfig

    model_config = ConfigDict(extra="forbid")


class DockerConfig(BaseModel):
    """Typed schema for `docker.yaml`."""

    refresh_time: PositiveInt
    registry_timeout: PositiveInt
    registry_endpoint: str
    registry_image_types: List[str]
    registry_address: str
    remote_api_timeout: PositiveInt
    remote_api_port: PositiveInt

    model_config = ConfigDict(extra="forbid")


class TritonConfig(BaseModel):
    """Typed schema for `triton.yaml`."""

    refresh_time: PositiveInt
    health_check_timeout: PositiveInt
    stream_timeout: PositiveInt
    http_infer_timeout: PositiveInt

    model_config = ConfigDict(extra="forbid")


class MinioConfig(BaseModel):
    """Typed schema for `minio.yaml`."""

    endpoint: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    secure: bool = True
    bucket: Optional[str] = None
    region: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


__all__ = [
    "JobsConfig",
    "WebsocketConfig",
    "DockerConfig",
    "TritonConfig",
    "MinioConfig",
]
