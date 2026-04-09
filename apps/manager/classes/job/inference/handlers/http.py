import logging
from typing import TYPE_CHECKING, Callable

import tritonclient.http as httpclient

from classes.triton.constants import HTTP_PORT
from classes.triton.inference_orchestrator import TritonInference, TritonRequest
from classes.triton.info.data.server import TritonServer
from classes.triton.tritonerrors import TritonInferenceFailed

from .base import check_instance, normalize_inference_payload, validate_fields

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

        payload = normalize_inference_payload(payload, self.docker)

        # Pipeline path (multi-model, sequential, HTTP only)
        steps_cfg = payload.get("pipeline")
        if isinstance(steps_cfg, list) and len(steps_cfg) > 0:
            vm_ip = payload.get("vm_ip")
            container_id = payload.get("container_id")
            if not vm_ip or not container_id:
                raise TritonInferenceFailed("pipeline", "Missing 'vm_ip' or 'container_id' for pipeline")

            check_instance(self.docker, vm_ip, container_id)

            if not self.triton:
                raise TritonInferenceFailed("pipeline", "No TritonThread available")

            server = self.triton.get_server(vm_ip, container_id)
            if not server:
                raise TritonInferenceFailed("pipeline", "No active Triton session for this instance")

            steps: list[TritonRequest] = []
            for step in steps_cfg:
                if isinstance(step, dict) and "inputs" in step:
                    step["inputs"] = (
                        normalize_inference_payload(
                            {
                                "container_id": container_id,
                                "vm_ip": vm_ip,
                                "request": {"inputs": step.get("inputs")},
                            },
                            self.docker,
                        )
                        .get("request", {})
                        .get("inputs", step.get("inputs"))
                    )
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
        allow_transient = bool(payload.get("request", {}).get("allow_transient"))
        if not allow_transient:
            check_instance(self.docker, vm_ip, container_id)

        if not self.triton:
            raise TritonInferenceFailed(model_name, "No TritonThread available")

        server = self.triton.get_server(vm_ip, container_id)
        if not server:
            if not allow_transient:
                raise TritonInferenceFailed(model_name, "No active Triton session for this instance")

            # Local-dev friendliness (explicit opt-in): allow inference without a prior
            # management "creation" flow by creating a transient TritonServer client.
            try:
                client = httpclient.InferenceServerClient(url=f"{vm_ip}:{HTTP_PORT}")
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
                    f"Failed to create transient Triton HTTP client: {exc}",
                )

        request = TritonRequest(
            model_name=model_name,
            inputs=inputs,
            protocol="http",
        )
        decoded = self.triton_inference.handle(server, request)

        logger.info(" ✓ HTTP inference complete for model '%s'", model_name)
        return decoded  # returned to handle_inference → sent as COMPLETED data
