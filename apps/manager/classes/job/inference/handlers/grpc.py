import logging
from typing import TYPE_CHECKING, Callable

import tritonclient.grpc as grpcclient

from classes.triton.constants import GRPC_PORT
from classes.triton.inference_orchestrator import TritonInference, TritonRequest
from classes.triton.info.data.server import TritonServer
from classes.triton.tritonerrors import TritonInferenceFailed
from utils.stream_cancel import clear as clear_cancel
from utils.stream_cancel import get_or_create as get_cancel_event

from .base import check_instance, enforce_payload_budget, normalize_inference_payload, validate_fields

if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.triton import TritonThread

logger = logging.getLogger(__name__)


class JobInferenceGrpc:
    """gRPC streaming inference handler."""

    _GRPC_CHANNEL_ARGS = [
        ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ("grpc.keepalive_time_ms", 30000),
        ("grpc.keepalive_timeout_ms", 10000),
        ("grpc.http2.min_ping_interval_without_data_ms", 5000),
    ]

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
        transient_server: TritonServer | None = None
        cancel_ev = get_cancel_event(msg_uuid)
        try:
            enforce_payload_budget(
                model_name,
                inputs,
                max_request_payload_mb=int(getattr(self.triton, "max_request_payload_mb", 0) or 0),
            )
            if not server:
                if not allow_transient:
                    raise TritonInferenceFailed(model_name, "No active Triton session for this instance")

                # Local-dev friendliness (explicit opt-in): allow streaming without a
                # pre-registered server by creating a transient TritonServer client.
                try:
                    try:
                        client = grpcclient.InferenceServerClient(
                            url=f"{vm_ip}:{GRPC_PORT}",
                            channel_args=self._GRPC_CHANNEL_ARGS,
                        )
                    except TypeError:
                        # Older tritonclient versions may not accept channel_args.
                        client = grpcclient.InferenceServerClient(url=f"{vm_ip}:{GRPC_PORT}")
                    # Fail fast on obviously unreachable endpoints (avoid "hung" streams).
                    connect_timeout = int(getattr(self.triton, "connection_timeout", 5))
                    try:
                        if not client.is_server_ready(client_timeout=connect_timeout):
                            raise TritonInferenceFailed(
                                model_name, f"Transient gRPC client not ready within {connect_timeout}s"
                            )
                    except TypeError:
                        # Older client versions may not support client_timeout on is_server_ready.
                        pass
                    transient_server = TritonServer(
                        vm_id="",
                        vm_ip=vm_ip,
                        container_id=container_id,
                        client=client,
                        model_name=model_name,
                        status="ready",
                        protocol="grpc",
                    )
                    server = transient_server
                except Exception as exc:
                    raise TritonInferenceFailed(
                        model_name,
                        f"Failed to create transient Triton gRPC client: {exc}",
                    )

            output_name = payload.get("request", {}).get("output_name", "output")

            if not send("START"):
                raise TritonInferenceFailed(model_name, "Stream aborted: client disconnected")

            request = TritonRequest(
                model_name=model_name,
                inputs=inputs,
                protocol="grpc",
                output_name=output_name,
                timeout=int(getattr(self.triton, "stream_timeout", 120)),
                tenant_id=str(((payload.get("_auth") or {}) or {}).get("tenant_id") or "unknown"),
                cancel_event=cancel_ev,
            )

            def _on_chunk(chunk) -> None:
                if not send("ONGOING", chunk):
                    # This will bubble up through TritonInfer.stream, triggering stop_stream().
                    raise TritonInferenceFailed(model_name, "Stream aborted: client disconnected")

            self.triton_inference.handle(server, request, on_chunk=_on_chunk)

            logger.info(" ✓ gRPC stream complete for model '%s'", model_name)
            return None  # COMPLETED data is null — all content sent via ONGOING
        finally:
            # Clear cancellation state for this client so future streams aren't pre-cancelled.
            clear_cancel(msg_uuid)
            # Explicitly close transient channel to avoid stream/client leaks.
            if transient_server is not None:
                try:
                    transient_server.close()
                except Exception:
                    pass
