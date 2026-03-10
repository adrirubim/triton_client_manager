import logging
from typing import TYPE_CHECKING, Callable

from classes.triton.inference_orchestrator import TritonInference, TritonRequest
from classes.triton.tritonerrors import TritonInferenceFailed

from .base import check_instance, validate_fields

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

        vm_ip, container_id, model_name, inputs = validate_fields(payload)
        check_instance(self.docker, vm_ip, container_id)

        if not self.triton:
            raise TritonInferenceFailed(model_name, "No TritonThread available")

        server = self.triton.get_server(vm_ip, container_id)
        if not server:
            raise TritonInferenceFailed(
                model_name, "No active Triton session for this instance"
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
