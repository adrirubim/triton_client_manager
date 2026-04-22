import logging
from typing import TYPE_CHECKING, Callable

import tritonclient.http as httpclient

from classes.triton.constants import HTTP_PORT
from classes.triton.inference_orchestrator import SHMReference, TritonInference, TritonRequest
from classes.triton.info.data.server import TritonServer
from classes.triton.tritonerrors import TritonInferenceFailed

from .base import check_instance, enforce_payload_budget, normalize_inference_payload, validate_fields

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
        tenant_id = str(((payload.get("_auth") or {}) or {}).get("tenant_id") or "unknown")

        # Multi-model inference sequence (sequential, HTTP only). External contract keeps `pipeline`.
        steps_cfg = payload.get("pipeline")
        if isinstance(steps_cfg, list) and len(steps_cfg) > 0:
            vm_ip = payload.get("vm_ip")
            container_id = payload.get("container_id")
            if not vm_ip or not container_id:
                raise TritonInferenceFailed("pipeline", "Missing 'vm_ip' or 'container_id' for pipeline")

            if not self.triton:
                raise TritonInferenceFailed("pipeline", "No TritonThread available")

            server = self.triton.get_server(vm_ip, container_id)
            if not server:
                raise TritonInferenceFailed("pipeline", "No active Triton session for this instance")

            inference_sequence: list[TritonRequest] = []
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
                inference_sequence.append(
                    TritonRequest(
                        name=step.get("name"),
                        model_name=step.get("model_name"),
                        inputs=step.get("inputs") or [],
                        protocol=(step.get("protocol") or "http"),
                        tenant_id=tenant_id,
                    )
                )

            # Admission control: enforce payload budget per step.
            max_mb = int(getattr(self.triton, "max_request_payload_mb", 0) or 0)
            for step in inference_sequence:
                enforce_payload_budget(step.model_name or "unknown", step.inputs or [], max_request_payload_mb=max_mb)

            # Validate instance after budget enforcement so stress tests can
            # validate 413 behavior without requiring a populated Docker cache.
            check_instance(self.docker, vm_ip, container_id)

            sequence_request = TritonRequest(pipeline=inference_sequence, tenant_id=tenant_id)
            decoded = self.triton_inference.handle(server, sequence_request)

            logger.info(" ✓ HTTP inference sequence complete for %d steps", len(inference_sequence))
            return decoded

        # Single-model path
        vm_ip, container_id, model_name, inputs = validate_fields(payload)
        allow_transient = bool(payload.get("request", {}).get("allow_transient"))

        if not self.triton:
            raise TritonInferenceFailed(model_name, "No TritonThread available")

        server = self.triton.get_server(vm_ip, container_id)
        transient_server: TritonServer | None = None
        try:
            enforce_payload_budget(
                model_name,
                inputs,
                max_request_payload_mb=int(getattr(self.triton, "max_request_payload_mb", 0) or 0),
            )
            if not allow_transient:
                # Validate after budget enforcement so 413 can be tested without Docker state.
                check_instance(self.docker, vm_ip, container_id)
            if not server:
                if not allow_transient:
                    raise TritonInferenceFailed(model_name, "No active Triton session for this instance")

                # Local-dev friendliness (explicit opt-in): allow inference without a prior
                # management "creation" flow by creating a transient TritonServer client.
                try:
                    connection_timeout = int(getattr(self.triton, "connection_timeout", 5))
                    network_timeout = int(getattr(self.triton, "network_timeout", 30))
                    client = httpclient.InferenceServerClient(
                        url=f"{vm_ip}:{HTTP_PORT}",
                        connection_timeout=connection_timeout,
                        network_timeout=network_timeout,
                    )
                    transient_server = TritonServer(
                        vm_id="",
                        vm_ip=vm_ip,
                        container_id=container_id,
                        client=client,
                        model_name=model_name,
                        status="ready",
                        protocol="http",
                        connection_timeout=connection_timeout,
                        network_timeout=network_timeout,
                    )
                    server = transient_server
                except Exception as exc:
                    raise TritonInferenceFailed(
                        model_name,
                        f"Failed to create transient Triton HTTP client: {exc}",
                    )

            shm_refs: list[SHMReference] = []
            raw_inputs: list[dict] = []
            if isinstance(inputs, list):
                for item in inputs:
                    if isinstance(item, dict) and {"shm_key", "offset", "byte_size", "shape", "dtype"}.issubset(
                        item.keys()
                    ):
                        shm_refs.append(
                            SHMReference(
                                name=str(item.get("name") or ""),
                                shm_key=str(item.get("shm_key") or ""),
                                offset=int(item.get("offset") or 0),
                                byte_size=int(item.get("byte_size") or 0),
                                shape=list(item.get("shape") or []),
                                dtype=str(item.get("dtype") or ""),
                            )
                        )
                    else:
                        raw_inputs.append(item)
            request = TritonRequest(
                model_name=model_name,
                inputs=raw_inputs if raw_inputs else inputs,
                shm_inputs=shm_refs or None,
                protocol="http",
                timeout=int(getattr(self.triton, "http_infer_timeout", 30)),
                tenant_id=tenant_id,
            )
            decoded = self.triton_inference.handle(server, request)

            logger.info(" ✓ HTTP inference complete for model '%s'", model_name)
            return decoded  # returned to handle_inference → sent as COMPLETED data
        finally:
            # Explicitly close transient client to avoid connection leaks.
            if transient_server is not None:
                try:
                    transient_server.close()
                except Exception:
                    pass
