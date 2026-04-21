import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass
class TritonServer:
    """Holds a persistent client and model config for one Triton container."""

    vm_id: str
    vm_ip: str
    container_id: str
    client: Any
    model_name: str = ""
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    status: str = "ready"
    protocol: Optional[Literal["http", "grpc"]] = None
    # Timeout governance (copied from triton.yaml at creation time when available).
    # Note: gRPC clients rely on per-call `client_timeout` rather than client-level timeouts.
    connection_timeout: int = 0
    network_timeout: int = 0
    consecutive_health_failures: int = 0
    last_healthy_ts: float = 0.0
    circuit_open_until_ts: float = 0.0
    consecutive_inference_failures: int = 0

    def has_changed(self, other: "TritonServer") -> tuple:
        changed_fields = []
        if self.status != other.status:
            changed_fields.append(f"status: {other.status} -> {self.status}")
        if self.model_name != other.model_name:
            changed_fields.append("model_name")
        if self.inputs != other.inputs:
            changed_fields.append("inputs")
        if self.outputs != other.outputs:
            changed_fields.append("outputs")
        return bool(changed_fields), changed_fields

    def close(self) -> None:
        try:
            if self.client is not None:
                self.client.close()
        except Exception as exc:
            logging.getLogger(__name__).warning("Error while closing Triton client in TritonServer.close: %s", exc)
