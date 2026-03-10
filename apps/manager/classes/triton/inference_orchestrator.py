from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from .infer import TritonInfer
from .info.data.server import TritonServer
from .tritonerrors import TritonInferenceFailed


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
    pipeline: Optional[List["TritonRequest"]] = None


class TritonInference:
    """Orchestrates inference pipelines on top of TritonInfer and TritonServer.

    This layer encapsulates:
      - protocol selection (HTTP vs gRPC streaming),
      - input encoding via TritonInfer,
      - basic error normalization via TritonInferenceFailed.
    """

    def __init__(self, runner: Optional[TritonInfer] = None) -> None:
        self._runner = runner or TritonInfer()

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

        # Pipeline support (HTTP only)
        if request.pipeline:
            results: dict[str, dict] = {}
            for step in request.pipeline:
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

        if protocol not in ("http", "grpc"):
            raise TritonInferenceFailed(
                request.model_name or "unknown",
                f"Unsupported inference protocol: {protocol!r}",
            )

        # Simple retry loop for transient failures
        attempts = max(0, request.retry_attempts) + 1

        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                if protocol == "http":
                    result = self.runner.infer(
                        server.client,
                        request.model_name or "",
                        request.inputs or [],
                        timeout=request.timeout,
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
                )
                return "".join(chunks)
            except TritonInferenceFailed as e:
                last_error = e
                continue

        # If we exit the loop without returning, re-raise last TritonInferenceFailed
        if last_error is not None:
            raise last_error

        raise TritonInferenceFailed(
            request.model_name or "unknown",
            "Inference failed without a specific TritonInferenceFailed error",
        )
