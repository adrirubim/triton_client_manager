from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

STATIC_START = "[TritonThread] "


@dataclass(frozen=True)
class TritonErrorContext:
    """Structured context for Triton-facing errors.

    This is intentionally stable and small to keep logs/metrics consistent.
    """

    model_name: str = "unknown"
    code: str = "TRITON_ERROR"
    retriable: bool = False
    reason: str = "Unknown"


class TritonError(Exception):
    """Base class for all typed Triton manager errors."""

    def __init__(
        self,
        *,
        model_name: str = "unknown",
        code: str = "TRITON_ERROR",
        reason: str = "Unknown",
        retriable: bool = False,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.model_name = model_name
        self.code = code
        self.retriable = bool(retriable)
        self.reason = reason
        self.cause = cause
        msg = f"{STATIC_START}{code}: model='{model_name}' retriable={self.retriable} reason={reason}"
        super().__init__(msg)

    @property
    def context(self) -> TritonErrorContext:
        return TritonErrorContext(
            model_name=self.model_name,
            code=self.code,
            retriable=self.retriable,
            reason=self.reason,
        )


class RetriableError(TritonError):
    """Errors that should be retried with backoff (network, timeout, overload)."""

    def __init__(
        self, *, model_name: str = "unknown", code: str, reason: str, cause: Optional[BaseException] = None
    ) -> None:
        super().__init__(model_name=model_name, code=code, reason=reason, retriable=True, cause=cause)


class FatalError(TritonError):
    """Errors that must NOT be retried (shape mismatch, model missing, auth failure)."""

    def __init__(
        self, *, model_name: str = "unknown", code: str, reason: str, cause: Optional[BaseException] = None
    ) -> None:
        super().__init__(model_name=model_name, code=code, reason=reason, retriable=False, cause=cause)


# -----------------------------
# Retriable error specializations
# -----------------------------
class TritonNetworkError(RetriableError):
    def __init__(
        self, model_name: str, reason: str = "Network error", *, cause: Optional[BaseException] = None
    ) -> None:
        super().__init__(model_name=model_name, code="TRITON_NETWORK", reason=reason, cause=cause)


class TritonTimeoutError(RetriableError):
    def __init__(self, model_name: str, reason: str = "Timeout", *, cause: Optional[BaseException] = None) -> None:
        super().__init__(model_name=model_name, code="TRITON_TIMEOUT", reason=reason, cause=cause)


class TritonOverloadedError(RetriableError):
    def __init__(
        self, model_name: str, reason: str = "Server overloaded", *, cause: Optional[BaseException] = None
    ) -> None:
        super().__init__(model_name=model_name, code="TRITON_OVERLOADED", reason=reason, cause=cause)


class TritonCircuitOpenError(RetriableError):
    def __init__(self, model_name: str, retry_after_seconds: int) -> None:
        self.retry_after_seconds = int(max(1, retry_after_seconds))
        # Keep the legacy string fragment to avoid breaking existing callers that parse it.
        reason = f"CIRCUIT_OPEN: retry_after={self.retry_after_seconds}s"
        super().__init__(model_name=model_name, code="TRITON_CIRCUIT_OPEN", reason=reason)


# -----------------------------
# Fatal error specializations
# -----------------------------
class TritonShapeMismatchError(FatalError):
    def __init__(self, model_name: str, reason: str) -> None:
        super().__init__(model_name=model_name, code="TRITON_SHAPE_MISMATCH", reason=reason)


class TritonModelMissingError(FatalError):
    def __init__(self, model_name: str, reason: str = "Model missing") -> None:
        super().__init__(model_name=model_name, code="TRITON_MODEL_MISSING", reason=reason)


class TritonAuthFailedError(FatalError):
    def __init__(self, model_name: str, reason: str = "Auth failure") -> None:
        super().__init__(model_name=model_name, code="TRITON_AUTH_FAILED", reason=reason)


class TritonServerHealthFailed(RetriableError):
    def __init__(self, timeout: int):
        self.timeout = timeout
        super().__init__(
            model_name="server",
            code="TRITON_SERVER_NOT_READY",
            reason=f"Server failed to become ready within {timeout}s",
        )


class TritonModelLoadFailed(FatalError):
    def __init__(self, model_name: str, reason: str = "Unknown"):
        self.model_name = model_name
        self.reason = reason
        super().__init__(model_name=model_name, code="TRITON_MODEL_LOAD_FAILED", reason=reason)


class TritonModelNotReady(RetriableError):
    def __init__(self, model_name: str, timeout: int):
        self.model_name = model_name
        self.timeout = timeout
        super().__init__(
            model_name=model_name,
            code="TRITON_MODEL_NOT_READY",
            reason=f"Model failed to become ready within {timeout}s",
        )


class TritonConfigDownloadFailed(RetriableError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            model_name="config",
            code="TRITON_CONFIG_DOWNLOAD_FAILED",
            reason=f"Failed to download model config from S3: {reason}",
        )


class TritonInferenceFailed(FatalError):
    def __init__(self, model_name: str, reason: str = "Unknown"):
        self.model_name = model_name
        self.reason = reason
        super().__init__(model_name=model_name, code="TRITON_INFERENCE_FAILED", reason=reason)


class TritonServerStateChanged(Exception):
    def __init__(self, vm_ip: str, container_id: str, changed_fields: list):
        self.vm_ip = vm_ip
        self.container_id = container_id
        self.changed_fields = changed_fields
        super().__init__(f"{STATIC_START}Server ({vm_ip}, {container_id[:12]}) state changed: {changed_fields}")


class TritonServerCreationFailed(FatalError):
    def __init__(self, vm_ip: str, container_id: str, reason: str):
        self.vm_ip = vm_ip
        self.container_id = container_id
        self.reason = reason
        super().__init__(
            model_name="server",
            code="TRITON_SERVER_CREATION_FAILED",
            reason=f"({vm_ip}, {container_id[:12]}): {reason}",
        )


class TritonMissingArgument(FatalError):
    def __init__(self, field: str):
        self.field = field
        super().__init__(
            model_name="manager", code="TRITON_MISSING_ARGUMENT", reason=f"Missing required argument: '{field}'"
        )


class TritonMissingInstance(FatalError):
    def __init__(self, vm_id: str, container_id: str):
        self.vm_id = vm_id
        self.container_id = container_id
        super().__init__(
            model_name="server",
            code="TRITON_MISSING_INSTANCE",
            reason=f"Server instance not found: vm_id='{vm_id}', container_id='{container_id}'",
        )
