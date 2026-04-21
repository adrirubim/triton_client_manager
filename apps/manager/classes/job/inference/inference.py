import logging
import time
from typing import TYPE_CHECKING, Callable

from classes.job.joberrors import JobInferenceMissingField
from classes.triton import TritonInfer
from classes.triton.inference_orchestrator import TritonInference
from classes.triton.tritonerrors import TritonError, TritonInferenceFailed
from utils.metrics import observe_inference_latency

from .handlers.grpc import JobInferenceGrpc
from .handlers.http import JobInferenceHttp

if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.openstack import OpenstackThread
    from classes.triton import TritonThread

###################################
#     Job Inference Handler       #
###################################

logger = logging.getLogger(__name__)


class JobInference:
    """Handles inference-type job requests"""

    def __init__(
        self,
        triton: "TritonThread",
        docker: "DockerThread",
        openstack: "OpenstackThread",
        websocket: Callable[[str, dict], bool],
    ):
        self.triton = triton
        self.docker = docker
        self.websocket = websocket
        self.openstack = openstack

        # Orchestration layer on top of TritonInfer
        self._triton_inference: TritonInference | None = None

        # Handlers are created lazily on first inference to support tests/mocks
        self._http: JobInferenceHttp | None = None
        self._grpc: JobInferenceGrpc | None = None

    def _ensure_handlers(self) -> None:
        """Initialize HTTP/GRPC handlers once TritonInfer is available.

        If tests or callers have already injected custom handlers into
        `self._http` / `self._grpc`, they are respected and not replaced.
        """
        # Respect pre-injected handlers (for tests/mocks)
        if self._http is not None and self._grpc is not None:
            return

        # NOTE: don't use isinstance() here.
        # In this repo we sometimes import `TritonInfer` through compatibility aliases (`classes.*`)
        # which can result in multiple class identities referring to the same implementation.
        infer_obj = getattr(self.triton, "triton_infer", None)
        if infer_obj is None:
            raise RuntimeError("TritonThread.triton_infer is not initialized")
        # Minimal structural check to fail fast on mis-wiring.
        if not callable(getattr(infer_obj, "decode_response", None)):
            raise RuntimeError("TritonThread.triton_infer is invalid (missing decode_response)")

        # Build orchestration layer and handlers (include circuit breaker governance if available)
        cb_fail = getattr(self.triton, "circuit_breaker_failure_threshold", 3)
        cb_open = getattr(self.triton, "circuit_breaker_open_seconds", 30)
        self._triton_inference = TritonInference(
            infer_obj,
            cb_failure_threshold=cb_fail,
            cb_open_seconds=cb_open,
        )
        self._http = JobInferenceHttp(self.docker, self._triton_inference, self.triton)
        self._grpc = JobInferenceGrpc(self.docker, self._triton_inference, self.triton)

    def handle_inference(self, msg: dict):
        """
        Orchestrate inference for a single message.

        Protocol selection:
          - Default: HTTP (single-shot)
          - gRPC streaming when payload.request.protocol == "grpc"
        """

        msg_uuid: str = msg.get("uuid", "")
        payload: dict = msg.get("payload", {}) or {}
        # Internal-only: attach auth context so lower layers can enrich metrics safely.
        # This is not part of the external SDK envelope returned to clients.
        payload["_auth"] = (msg.get("_auth") or {}) or {}
        tenant_id = str(((msg.get("_auth") or {}) or {}).get("tenant_id") or "unknown")

        if not msg_uuid:
            raise JobInferenceMissingField("uuid")

        # Determine protocol (http | grpc)
        self._ensure_handlers()
        request_cfg = payload.get("request", {}) or {}
        protocol = (request_cfg.get("protocol") or "http").lower()

        if protocol not in ("http", "grpc"):
            error = f"Unsupported inference protocol: {protocol!r}"
            logger.warning("JobInference: %s", error)
            self.websocket(msg_uuid, self._make_payload(msg_uuid, "FAILED", None, error))
            return

        # Helper used by gRPC handler to stream chunks
        def send(status: str, data=None, model_name: str | None = None) -> bool:
            return bool(
                self.websocket(
                msg_uuid,
                self._make_payload(msg_uuid, status, model_name, data),
            )
            )

        start = time.perf_counter()
        model_name_for_metrics = payload.get("model_name") or "unknown"
        try:
            if protocol == "http":
                decoded = self._http.handle(msg_uuid, payload, send)
                # HTTP is single-shot: one COMPLETED message with full data
                # model_name is already validated inside handler; reuse from payload
                model_name = payload.get("model_name")
                self.websocket(
                    msg_uuid,
                    self._make_payload(msg_uuid, "COMPLETED", model_name, decoded),
                )
            else:
                # gRPC streaming: handler sends START + multiple ONGOING
                self._grpc.handle(msg_uuid, payload, send)
                model_name = payload.get("model_name")
                self.websocket(
                    msg_uuid,
                    self._make_payload(msg_uuid, "COMPLETED", model_name, None),
                )

        except JobInferenceMissingField as e:
            logger.warning("JobInference missing field: %s", e)
            self.websocket(
                msg_uuid,
                self._make_payload(msg_uuid, "FAILED", None, str(e)),
            )
        except ValueError as e:
            # Validation errors (missing fields, unknown container, etc.) are expected in dev/stress runs.
            # Avoid stack traces: they add overhead under load and can starve the executor.
            self.websocket(
                msg_uuid,
                self._make_payload(msg_uuid, "FAILED", None, str(e)),
            )
        except TritonError as e:
            # Stable, typed error contract for all Triton-facing errors.
            # Never rely on string parsing for downstream SDK behavior.
            retry_after = getattr(e, "retry_after_seconds", None)
            data = {
                "code": getattr(e, "code", "TRITON_ERROR"),
                "message": str(e),
                "retriable": bool(getattr(e, "retriable", False)),
            }
            if retry_after is not None:
                try:
                    data["retry_after_seconds"] = int(retry_after)
                except Exception:
                    # Keep as-is if it can't be coerced; still present.
                    data["retry_after_seconds"] = retry_after

            logger.warning(
                "Triton inference error (code=%s retriable=%s tenant=%s): %s",
                data.get("code"),
                data.get("retriable"),
                tenant_id,
                str(e),
            )
            self.websocket(
                msg_uuid,
                self._make_payload(
                    msg_uuid,
                    "FAILED",
                    getattr(e, "model_name", None),
                    data,
                ),
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Unexpected inference error")
            self.websocket(
                msg_uuid,
                self._make_payload(msg_uuid, "FAILED", None, f"Unexpected error: {e}"),
            )
        finally:
            elapsed = time.perf_counter() - start
            observe_inference_latency(model_name_for_metrics, elapsed, tenant_id=tenant_id)

    # -------------------------------------------- #
    #              WEBSOCKET HELPERS                #
    # -------------------------------------------- #
    def _make_payload(self, msg_uuid: str, status: str, model_name: str, data) -> dict:
        return {
            "type": "inference",
            "uuid": msg_uuid,
            "payload": {"data": data, "status": status, "model_name": model_name},
        }
