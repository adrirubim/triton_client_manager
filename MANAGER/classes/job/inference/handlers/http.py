import logging
from typing import TYPE_CHECKING, Callable

from classes.triton import TritonInfer
from classes.triton.tritonerrors import TritonInferenceFailed

from .base import check_instance, validate_fields

if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.triton import TritonThread

logger = logging.getLogger(__name__)


class JobInferenceHttp:
    """HTTP single-shot inference handler."""

    def __init__(
        self, docker: "DockerThread", triton_infer: TritonInfer, triton: "TritonThread" = None
    ):
        self.docker = docker
        self.triton_infer = triton_infer
        self.triton = triton

    def handle(self, msg_uuid: str, payload: dict, send: Callable) -> dict:
        logger.info(" Running HTTP inference...")

        vm_ip, container_id, model_name, inputs = validate_fields(payload)
        check_instance(self.docker, vm_ip, container_id)

        if not self.triton:
            raise TritonInferenceFailed(model_name, "No TritonThread available")

        server = self.triton.get_server(vm_ip, container_id)
        if not server:
            raise TritonInferenceFailed(model_name, "No active Triton session for this instance")

        result = self.triton_infer.infer(server.client, model_name, inputs)
        decoded = TritonInfer.decode_response(result)

        logger.info(" ✓ HTTP inference complete for model '{model_name}'")
        return decoded  # returned to handle_inference → sent as COMPLETED data
