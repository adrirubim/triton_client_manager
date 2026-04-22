from __future__ import annotations

import contextlib
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from utils.metrics import observe_circuit_open, observe_inference_duration, observe_inference_error

from .infer import TritonInfer
from .info.data.server import TritonServer
from .tritonerrors import (
    FatalError,
    TritonAuthFailedError,
    TritonCircuitOpenError,
    TritonError,
    TritonInferenceFailed,
    TritonModelMissingError,
    TritonNetworkError,
    TritonOverloadedError,
    TritonTimeoutError,
)

logger = logging.getLogger(__name__)

# Inference retries run inside bounded thread pool workers. Sleeping for large
# backoff windows inside a worker directly reduces concurrency and can cause
# starvation under incident conditions. Keep a tiny blocking budget only.
MAX_BLOCKING_BACKOFF_SECONDS = 0.10


@dataclass
class TritonRequest:
    """High-level description of an inference request for a TritonServer.

    Supports both single-model and simple multi-model (pipeline) requests:
      - single-model: set model_name + inputs;
      - pipeline: set pipeline=[TritonRequest(...), ...].
    """

    model_name: Optional[str] = None
    inputs: Optional[List[dict]] = None
    name: Optional[str] = None
    inputs_from: Optional[str] = None
    input_mapping: Optional[dict] = None
    protocol: str = "http"
    output_name: str = "output"
    timeout: int = 30
    retry_attempts: int = 0
    tenant_id: Optional[str] = None
    cancel_event: Optional[threading.Event] = None
    pipeline: Optional[List["TritonRequest"]] = None


class TritonInference:
    """Orchestrates inference pipelines on top of TritonInfer and TritonServer.

    This layer encapsulates:
      - protocol selection (HTTP vs gRPC streaming),
      - input encoding via TritonInfer,
      - basic error normalization via TritonInferenceFailed.
    """

    def __init__(
        self,
        runner: Optional[TritonInfer] = None,
        *,
        cb_failure_threshold: int = 3,
        cb_open_seconds: int = 30,
    ) -> None:
        self._runner = runner or TritonInfer()
        # Circuit breaker settings (governed by triton.yaml via TritonThread).
        self._cb_failure_threshold = int(cb_failure_threshold)
        self._cb_open_seconds = int(cb_open_seconds)

    @property
    def runner(self) -> TritonInfer:
        return self._runner

    def handle(
        self,
        server: TritonServer,
        request: TritonRequest,
        on_chunk: Optional[Callable[[str], None]] = None,
    ):
        """Execute inference on the given TritonServer according to TritonRequest.

        - Single-model HTTP: returns a decoded dict of outputs.
        - Single-model gRPC:
            - if on_chunk is provided, it is called for each decoded chunk and
              the method returns None (streaming path);
            - if on_chunk is None, chunks are accumulated and a single str is
              returned (convenience path for simple callers).
        - Pipeline (multi-model, HTTP only for now): executes each step
          sequentially and returns a dict {model_name: decoded_outputs}.
        """

        # Multi-model sequence support (HTTP only). External contract keeps the `pipeline` field.
        if request.pipeline:
            results: dict[str, dict] = {}
            inference_sequence = request.pipeline
            for step in inference_sequence:
                if (step.protocol or "http").lower() != "http":
                    raise TritonInferenceFailed(
                        step.model_name or "unknown",
                        "Pipelines currently support only HTTP steps",
                    )
                single = TritonRequest(
                    model_name=step.model_name,
                    inputs=step.inputs,
                    name=step.name,
                    protocol="http",
                    timeout=step.timeout,
                    retry_attempts=step.retry_attempts,
                )
                decoded = self._handle_single(server, single, on_chunk=None)
                step_name = single.name or single.model_name or ""
                results[step_name] = decoded
            return results

        # Single-model path
        return self._handle_single(server, request, on_chunk)

    def _handle_single(
        self,
        server: TritonServer,
        request: TritonRequest,
        on_chunk: Optional[Callable[[str], None]],
    ):
        protocol = (request.protocol or "http").lower()
        model_name = request.model_name or "unknown"
        tenant_id = str(request.tenant_id or "unknown")
        started = time.perf_counter()

        if protocol not in ("http", "grpc"):
            raise TritonInferenceFailed(
                request.model_name or "unknown",
                f"Unsupported inference protocol: {protocol!r}",
            )

        attempts = max(0, request.retry_attempts) + 1
        last_error: TritonError | None = None

        for attempt_idx in range(attempts):
            try:
                # Circuit breaker: if open, fail fast with retry hint.
                now = time.time()
                open_until = float(getattr(server, "circuit_open_until_ts", 0.0) or 0.0)
                if open_until and now < open_until:
                    retry_after = int(max(1, open_until - now))
                    raise TritonCircuitOpenError(request.model_name or "unknown", retry_after_seconds=retry_after)

                if protocol == "http":
                    result = self.runner.infer(
                        server.client,
                        request.model_name or "",
                        request.inputs or [],
                        timeout=request.timeout,
                    )
                    # Success closes breaker.
                    server.consecutive_inference_failures = 0
                    server.circuit_open_until_ts = 0.0
                    observe_inference_duration(
                        model_name,
                        protocol,
                        "ok",
                        time.perf_counter() - started,
                        code="OK",
                        tenant_id=tenant_id,
                    )
                    return TritonInfer.decode_response(result)

                # gRPC streaming
                if on_chunk is not None:
                    self.runner.stream(
                        server.client,
                        request.model_name or "",
                        request.inputs or [],
                        on_chunk=on_chunk,
                        output_name=request.output_name,
                        timeout=request.timeout,
                        cancel_event=request.cancel_event,
                    )
                    server.consecutive_inference_failures = 0
                    server.circuit_open_until_ts = 0.0
                    observe_inference_duration(
                        model_name,
                        protocol,
                        "ok",
                        time.perf_counter() - started,
                        code="OK",
                        tenant_id=tenant_id,
                    )
                    return None

                # Convenience path: accumulate chunks when no callback is provided.
                chunks: list[str] = []

                def _collect(chunk: str) -> None:
                    chunks.append(chunk)

                self.runner.stream(
                    server.client,
                    request.model_name or "",
                    request.inputs or [],
                    on_chunk=_collect,
                    output_name=request.output_name,
                    timeout=request.timeout,
                    cancel_event=request.cancel_event,
                )
                server.consecutive_inference_failures = 0
                server.circuit_open_until_ts = 0.0
                observe_inference_duration(
                    model_name,
                    protocol,
                    "ok",
                    time.perf_counter() - started,
                    code="OK",
                    tenant_id=tenant_id,
                )
                return "".join(chunks)
            except Exception as exc:  # noqa: BLE001
                err = self._classify_error(model_name=(request.model_name or "unknown"), exc=exc)
                last_error = err
                observe_inference_error(
                    err.model_name,
                    err.code,
                    retriable=err.retriable,
                    protocol=protocol,
                    tenant_id=tenant_id,
                )

                # Fatal errors fail fast: no retries, no breaker churn.
                if isinstance(err, FatalError):
                    observe_inference_duration(
                        model_name,
                        protocol,
                        "error",
                        time.perf_counter() - started,
                        code=err.code,
                        tenant_id=tenant_id,
                    )
                    raise err

                # Record retriable failure; open circuit if threshold reached.
                fails = int(getattr(server, "consecutive_inference_failures", 0) or 0) + 1
                server.consecutive_inference_failures = fails
                if fails >= self._cb_failure_threshold:
                    now = time.time()
                    server.circuit_open_until_ts = now + float(self._cb_open_seconds)
                    observe_circuit_open(err.model_name, err.code)
                    # Fail fast with stable, typed error (keeps legacy retry_after string).
                    observe_inference_duration(
                        model_name,
                        protocol,
                        "error",
                        time.perf_counter() - started,
                        code="TRITON_CIRCUIT_OPEN",
                        tenant_id=tenant_id,
                    )
                    raise TritonCircuitOpenError(err.model_name, retry_after_seconds=int(self._cb_open_seconds))

                # Retry only on retriable errors, with exponential backoff + jitter.
                if attempt_idx < (attempts - 1):
                    delay = self._backoff_delay_seconds(attempt_idx)
                    budget = float(min(float(delay), MAX_BLOCKING_BACKOFF_SECONDS))
                    if delay > budget:
                        logger.warning(
                            "AUDIT_INFERENCE_BACKOFF_TRUNCATED: requested=%.3fs applied=%.3fs thread=%s",
                            float(delay),
                            float(budget),
                            threading.current_thread().name,
                        )
                    if budget > 0:
                        time.sleep(budget)
                    continue
                observe_inference_duration(
                    model_name,
                    protocol,
                    "error",
                    time.perf_counter() - started,
                    code=err.code,
                    tenant_id=tenant_id,
                )
                raise err

        # If we exit the loop without returning, re-raise last typed error
        if last_error is not None:
            observe_inference_duration(
                model_name,
                protocol,
                "error",
                time.perf_counter() - started,
                code=last_error.code,
                tenant_id=tenant_id,
            )
            raise last_error

        raise TritonInferenceFailed(
            request.model_name or "unknown",
            "Inference failed without a specific TritonInferenceFailed error",
        )

    @staticmethod
    def _backoff_delay_seconds(attempt_idx: int) -> float:
        """
        Exponential backoff with jitter.
        attempt_idx=0 => first retry delay.
        """
        base = 0.10
        cap = 2.0
        exp = min(cap, base * (2 ** max(0, int(attempt_idx))))
        jitter = random.uniform(0.0, exp * 0.25)  # nosec B311 - non-crypto jitter
        return float(min(cap, exp + jitter))

    @staticmethod
    def _classify_error(*, model_name: str, exc: BaseException) -> TritonError:
        """
        Normalize arbitrary exceptions into typed TritonError classes.

        Constraint: keep contract incremental (don't change SDK envelope).
        """
        if isinstance(exc, TritonError):
            return exc

        # --- Native mapping: Triton client exception codes (HTTP/gRPC) ---
        with contextlib.suppress(Exception):
            from tritonclient.utils import InferenceServerException  # type: ignore

            if isinstance(exc, InferenceServerException):
                status = getattr(exc, "status", None)
                try:
                    status_int = int(status) if status is not None else None
                except Exception:
                    status_int = None

                msg = str(exc) or ""
                if status_int in (401, 403):
                    return TritonAuthFailedError(model_name, msg or "Auth failed")
                if status_int == 404:
                    return TritonModelMissingError(model_name, msg or "Model missing")
                if status_int in (408, 504):
                    return TritonTimeoutError(model_name, msg or "Timeout", cause=exc)
                if status_int in (429, 503):
                    return TritonOverloadedError(model_name, msg or "Server unavailable/overloaded", cause=exc)
                if status_int is not None and 500 <= status_int <= 599:
                    return TritonNetworkError(model_name, msg or "Server error", cause=exc)
                # Unknown status -> default fatal inference failure
                return TritonInferenceFailed(model_name, msg)

        # --- Native mapping: gRPC status codes ---
        with contextlib.suppress(Exception):
            import grpc  # type: ignore

            if isinstance(exc, grpc.RpcError):
                code = exc.code()
                details = exc.details() if hasattr(exc, "details") else str(exc)
                if code in (grpc.StatusCode.DEADLINE_EXCEEDED,):
                    return TritonTimeoutError(model_name, details or "gRPC deadline exceeded", cause=exc)
                if code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.CANCELLED):
                    return TritonNetworkError(model_name, details or "gRPC unavailable", cause=exc)
                if code in (grpc.StatusCode.RESOURCE_EXHAUSTED,):
                    return TritonOverloadedError(model_name, details or "gRPC resource exhausted", cause=exc)
                if code in (grpc.StatusCode.NOT_FOUND,):
                    return TritonModelMissingError(model_name, details or "Model missing")
                if code in (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED):
                    return TritonAuthFailedError(model_name, details or "Auth failed")
                return TritonInferenceFailed(model_name, details or "gRPC error")

        msg = str(exc) or ""
        low = msg.lower()

        # Common timeout signals (grpc / aiohttp / http clients)
        if "timed out" in low or "timeout" in low or "deadline exceeded" in low:
            return TritonTimeoutError(model_name, msg, cause=exc)

        # Overload / throttling signals
        if "overloaded" in low or "unavailable" in low or "resource exhausted" in low or "too many requests" in low:
            return TritonOverloadedError(model_name, msg, cause=exc)

        # Model missing / not found signals (best-effort string matching; stable error type)
        if "not found" in low and "model" in low:
            return TritonModelMissingError(model_name, msg)

        # Network / connection failures
        if "connection" in low or "unreachable" in low or "refused" in low or "reset" in low:
            return TritonNetworkError(model_name, msg, cause=exc)

        # Default: fatal inference failure (unknown classification)
        return TritonInferenceFailed(model_name, msg)
