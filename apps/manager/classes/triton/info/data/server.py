from dataclasses import dataclass, field
from typing import Union

import tritonclient.grpc as grpcclient
import tritonclient.http as httpclient


@dataclass
class TritonServer:
    """Holds a persistent client and model config for one Triton container."""

    vm_id: str
    vm_ip: str
    container_id: str
    client: Union[grpcclient.InferenceServerClient, httpclient.InferenceServerClient]
    model_name: str = ""
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    status: str = "ready"

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
            self.client.close()
        except Exception:
            pass
