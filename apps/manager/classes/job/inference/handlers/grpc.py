import logging
from typing import TYPE_CHECKING, Callable

import tritonclient.grpc as grpcclient

from classes.triton.constants import GRPC_PORT
from classes.triton.inference_orchestrator import TritonInference, TritonRequest
from classes.triton.info.data.server import TritonServer
from classes.triton.tritonerrors import TritonInferenceFailed

from .base import check_instance, normalize_inference_payload, validate_fields

if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.triton import TritonThread

logger = logging.getLogger(__name__)


class JobInferenceGrpc:
    """gRPC streaming inference handler."""

    def __init__(
        self,
        docker: "DockerThread",
        triton_infer_or_inference,
        triton: "TritonThread" = None,
    ):
        self.docker = docker
        # Backwards compatibility: accept either TritonInfer or TritonInference
        if isinstance(triton_infer_or_inference, TritonInference):
            self.triton_inference = triton_infer_or_inference
        else:
            self.triton_inference = TritonInference(triton_infer_or_inference)
        self.triton = triton

    def handle(self, msg_uuid: str, payload: dict, send: Callable) -> None:
        logger.info(" Running gRPC inference...")

        payload = normalize_inference_payload(payload, self.docker)
        vm_ip, container_id, model_name, inputs = validate_fields(payload)
        allow_transient = bool(payload.get("request", {}).get("allow_transient"))
        if not allow_transient:
            check_instance(self.docker, vm_ip, container_id)

        if not self.triton:
            raise TritonInferenceFailed(model_name, "No TritonThread available")

        server = self.triton.get_server(vm_ip, container_id)
        if not server:
            if not allow_transient:
                raise TritonInferenceFailed(model_name, "No active Triton session for this instance")

            # Local-dev friendliness (explicit opt-in): allow streaming without a
            # pre-registered server by creating a transient TritonServer client.
            try:
                client = grpcclient.InferenceServerClient(url=f"{vm_ip}:{GRPC_PORT}")
                server = TritonServer(
                    vm_id="",
                    vm_ip=vm_ip,
                    container_id=container_id,
                    client=client,
                    model_name=model_name,
                    status="ready",
                )
            except Exception as exc:
                raise TritonInferenceFailed(
                    model_name,
                    f"Failed to create transient Triton gRPC client: {exc}",
                )

        output_name = payload.get("request", {}).get("output_name", "output")

        send("START")

        request = TritonRequest(
            model_name=model_name,
            inputs=inputs,
            protocol="grpc",
            output_name=output_name,
        )

        self.triton_inference.handle(
            server,
            request,
            on_chunk=lambda chunk: send("ONGOING", chunk),
        )

        logger.info(" ✓ gRPC stream complete for model '%s'", model_name)
        return None  # COMPLETED data is null — all content sent via ONGOING
