from typing import Dict, List, Optional

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, PositiveInt


class JobsQoSConfig(BaseModel):
    """QoS governance for multi-tenant scheduling."""

    # DRR governance
    base_quantum: int = Field(
        default=10,
        description="Base quantum added to each tenant deficit per scheduler cycle (cost units)",
    )
    job_type_costs: Dict[str, int] = Field(
        default_factory=lambda: {"inference": 10, "management": 5, "info": 1},
        description="Cost per dispatched job by type (cost units)",
    )
    tenant_quantum_multipliers: Dict[str, int] = Field(
        default_factory=dict,
        description="Optional per-tenant quantum multipliers (tenant_id -> multiplier)",
    )

    job_type_weights: Dict[str, int] = Field(
        default_factory=lambda: {"inference": 5, "management": 2, "info": 1},
        description="Relative weights per job_type for scheduler slot allocation",
    )
    tenant_weights: Dict[str, int] = Field(
        default_factory=dict,
        description="Optional per-tenant weight overrides (tenant_id -> weight)",
    )

    model_config = ConfigDict(extra="forbid")


class JobsConfig(BaseModel):
    """Typed schema for jobs.yaml."""

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

    qos: JobsQoSConfig = Field(default_factory=JobsQoSConfig)

    model_config = ConfigDict(extra="forbid")


class WebsocketAuthConfig(BaseModel):
    """`auth` subsection of websocket.yaml."""

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
    """`rate_limits` subsection of websocket.yaml."""

    messages_per_second_per_client: int = 0
    auth_failures_per_minute_per_client: int = 0
    messages_per_second_per_tenant: int = 0

    model_config = ConfigDict(extra="forbid")


class WebsocketConfig(BaseModel):
    """Typed schema for websocket.yaml."""

    host: str
    port: PositiveInt
    valid_types: List[str]
    max_message_bytes: PositiveInt
    auth: WebsocketAuthConfig
    rate_limits: WebsocketRateLimitsConfig

    model_config = ConfigDict(extra="forbid")


class DockerConfig(BaseModel):
    """Typed schema for docker.yaml."""

    refresh_time: PositiveInt
    registry_timeout: PositiveInt
    registry_endpoint: str
    registry_image_types: List[str]
    registry_address: str
    remote_api_timeout: PositiveInt
    remote_api_port: PositiveInt

    model_config = ConfigDict(extra="forbid")


class TritonConfig(BaseModel):
    """Typed schema for triton.yaml."""

    refresh_time: PositiveInt
    health_check_timeout: PositiveInt
    stream_timeout: PositiveInt
    http_infer_timeout: PositiveInt

    # Auto-healing / stale eviction governance (Phase 8.5+)
    health_failure_evict_threshold: PositiveInt = Field(
        default=3,
        description="Evict a TritonServer after N consecutive failed health checks",
    )
    stale_evict_seconds: PositiveInt = Field(
        default=300,
        description="Evict a TritonServer if it has not been healthy for this many seconds",
    )
    active_heal_restart_threshold: PositiveInt = Field(
        default=2,
        description="Attempt container restart after N consecutive failed health checks",
    )
    active_heal_restart_cooldown_seconds: PositiveInt = Field(
        default=300,
        description="Cooldown between restart attempts for the same container_id",
    )

    # Circuit breaker governance (inference)
    circuit_breaker_failure_threshold: PositiveInt = Field(
        default=3,
        description="Open circuit after N consecutive inference failures per server",
    )
    circuit_breaker_open_seconds: PositiveInt = Field(
        default=30,
        description="How long the circuit remains open (fail-fast) before retrying",
    )

    model_config = ConfigDict(extra="forbid")


class MinioConfig(BaseModel):
    """Typed schema for minio.yaml (optional)."""

    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    region: Optional[str] = None

    model_config = ConfigDict(extra="forbid")
