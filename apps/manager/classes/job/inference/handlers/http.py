import logging
from typing import TYPE_CHECKING, Callable

from classes.triton.inference_orchestrator import TritonInference, TritonRequest
from classes.triton.tritonerrors import TritonInferenceFailed

from .base import check_instance, validate_fields

if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.triton import TritonThread

logger = logging.getLogger(__name__)


class JobInferenceHttp:
    """HTTP single-shot inference handler."""

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

    def handle(self, msg_uuid: str, payload: dict, send: Callable) -> dict:
        logger.info(" Running HTTP inference...")

        # Pipeline path (multi-model, sequential, HTTP only)
        if "pipeline" in payload:
            vm_ip = payload.get("vm_ip")
            container_id = payload.get("container_id")
            if not vm_ip or not container_id:
                raise TritonInferenceFailed(
                    "pipeline", "Missing 'vm_ip' or 'container_id' for pipeline"
                )

            check_instance(self.docker, vm_ip, container_id)

            if not self.triton:
                raise TritonInferenceFailed("pipeline", "No TritonThread available")

            server = self.triton.get_server(vm_ip, container_id)
            if not server:
                raise TritonInferenceFailed(
                    "pipeline", "No active Triton session for this instance"
                )

            steps_cfg = payload.get("pipeline") or []
            steps: list[TritonRequest] = []
            for step in steps_cfg:
                steps.append(
                    TritonRequest(
                        name=step.get("name"),
                        model_name=step.get("model_name"),
                        inputs=step.get("inputs") or [],
                        protocol=(step.get("protocol") or "http"),
                    )
                )

            pipeline_request = TritonRequest(pipeline=steps)
            decoded = self.triton_inference.handle(server, pipeline_request)

            logger.info(" ✓ HTTP pipeline inference complete for %d steps", len(steps))
            return decoded

        # Single-model path
        vm_ip, container_id, model_name, inputs = validate_fields(payload)
        check_instance(self.docker, vm_ip, container_id)

        if not self.triton:
            raise TritonInferenceFailed(model_name, "No TritonThread available")

        server = self.triton.get_server(vm_ip, container_id)
        if not server:
            raise TritonInferenceFailed(
                model_name, "No active Triton session for this instance"
            )

        request = TritonRequest(
            model_name=model_name,
            inputs=inputs,
            protocol="http",
        )
        decoded = self.triton_inference.handle(server, request)

        logger.info(" ✓ HTTP inference complete for model '{model_name}'")
        return decoded  # returned to handle_inference → sent as COMPLETED data
