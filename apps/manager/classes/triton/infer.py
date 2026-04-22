import contextlib
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import tritonclient.grpc as grpcclient
import tritonclient.http as httpclient
import tritonclient.utils.shared_memory as shm

from utils.metrics import observe_grpc_stream_failure

from .constants import TYPE_MAP
from .tritonerrors import (
    TritonError,
    TritonInferenceFailed,
    TritonShapeMismatchError,
    TritonSHMRegistrationFailed,
    TritonSHMUnavailable,
)

logger = logging.getLogger(__name__)

###################################
#      Triton Inference Runner    #
###################################

STREAM_TIMEOUT = 120  # seconds before a hung gRPC stream is abandoned

# POSIX SHM root directory (Linux). Bandit B108 flags hardcoded tmp dirs, but
# for Triton System Shared Memory this path is intentional and part of the contract.
SHM_ROOT = "/dev/shm"  # nosec B108

# NOTE: We intentionally avoid importing numpy at module import time.
# These are "static" structures used to reduce per-request allocations.
_DTYPE_NAME_BY_TRITON_TYPE: dict[str, str] = {
    "BOOL": "bool_",
    "INT8": "int8",
    "INT16": "int16",
    "INT32": "int32",
    "INT64": "int64",
    "UINT8": "uint8",
    "UINT16": "uint16",
    "UINT32": "uint32",
    "UINT64": "uint64",
    "FP16": "float16",
    "FP32": "float32",
    "FP64": "float64",
}


class TritonInfer:
    """Sends inference requests to Triton — gRPC streaming (LLM) or HTTP (ML)."""

    def __init__(self, *, shm_cache_max_regions: int = 256) -> None:
        # Per-process SHM registration manager (thread-safe).
        self._shm = TritonSHMManager(max_regions_per_client=int(shm_cache_max_regions))

    @staticmethod
    def _np():
        import numpy as np  # heavy import (lazy)

        return np

    @staticmethod
    def _grpcclient():
        return grpcclient

    @staticmethod
    def _httpclient():
        return httpclient

    @staticmethod
    def _to_numpy(datatype: str, value):
        """
        Avoid corrupting tensor dimensions by wrapping everything in [value].
        - If value is list/tuple/np.ndarray: np.asarray(value)
        - If scalar: np.asarray([value]) (preserves a batch-like dimension)
        Special case BYTES: produce dtype=object and encode strings.
        """
        np = TritonInfer._np()
        if datatype == "BYTES":
            if isinstance(value, (list, tuple, np.ndarray)):
                encoded = [v.encode("utf-8") if isinstance(v, str) else v for v in np.asarray(value).tolist()]
                return np.asarray(encoded, dtype=object)
            return np.asarray(
                [value.encode("utf-8") if isinstance(value, str) else value],
                dtype=object,
            )

        dtype_name = _DTYPE_NAME_BY_TRITON_TYPE.get(str(datatype or "").upper())
        np_dtype = getattr(np, dtype_name) if dtype_name else None

        if isinstance(value, (list, tuple, np.ndarray)):
            return np.asarray(value, dtype=np_dtype) if np_dtype is not None else np.asarray(value)
        return np.asarray([value], dtype=np_dtype) if np_dtype is not None else np.asarray([value])

    @staticmethod
    def _validate_shape(name: str, expected_shape: list[int], data) -> None:
        """
        Validate that the numpy payload matches the declared Triton dims.

        This is a strict guardrail: mismatched shapes become hard errors BEFORE
        we hit Triton, because Triton errors are slower and harder to debug.
        """
        np = TritonInfer._np()
        if not isinstance(expected_shape, list) or any(not isinstance(d, int) for d in expected_shape):
            raise TritonShapeMismatchError(
                "unknown", f"Invalid dims for input {name!r}: expected list[int], got {expected_shape!r}"
            )
        if not isinstance(data, np.ndarray):
            raise TritonShapeMismatchError(
                "unknown",
                f"Invalid numpy payload for input {name!r}: expected np.ndarray, got {type(data)!r}",
            )

        # Strict: do not allow implicit reshapes. Caller must supply consistent dims/value.
        if tuple(data.shape) != tuple(expected_shape):
            raise TritonShapeMismatchError(
                "unknown",
                f"Input shape mismatch for {name!r}: dims={expected_shape} vs value.shape={list(data.shape)}",
            )

    # -------------------------------------------- #
    #               INPUT BUILDERS                  #
    # -------------------------------------------- #
    @staticmethod
    def _build_grpc_inputs(inputs: list) -> list:
        """Convert payload inputs to tritonclient.grpc InferInput objects."""
        grpcclient = TritonInfer._grpcclient()
        grpc_inputs = []
        for inp in inputs:
            dims = inp["dims"]
            shape = [dims] if isinstance(dims, int) else list(dims)
            datatype = TYPE_MAP.get(inp["type"], inp["type"])
            value = inp["value"]

            infer_input = grpcclient.InferInput(inp["name"], shape, datatype)

            data = TritonInfer._to_numpy(datatype, value)
            TritonInfer._validate_shape(inp["name"], shape, data)

            infer_input.set_data_from_numpy(data)
            grpc_inputs.append(infer_input)

        return grpc_inputs

    @staticmethod
    def _build_http_inputs(inputs: list) -> list:
        """Convert payload inputs to tritonclient.http InferInput objects."""
        httpclient = TritonInfer._httpclient()
        http_inputs = []
        for inp in inputs:
            dims = inp["dims"]
            shape = [dims] if isinstance(dims, int) else list(dims)
            datatype = TYPE_MAP.get(inp["type"], inp["type"])
            value = inp["value"]

            infer_input = httpclient.InferInput(inp["name"], shape, datatype)

            data = TritonInfer._to_numpy(datatype, value)
            TritonInfer._validate_shape(inp["name"], shape, data)

            infer_input.set_data_from_numpy(data)
            http_inputs.append(infer_input)

        return http_inputs

    # -------------------------------------------- #
    #            OUTPUT DECODERS                   #
    # -------------------------------------------- #
    @staticmethod
    def decode_output(result, output_name: str):
        """Decode a single named output tensor to a Python-native type.

        BYTES  → str (single) or list[str]
        FP16   → cast to FP32 → float / list[float]
        others → .tolist() (int, float, bool)
        """
        arr = result.as_numpy(output_name)
        np = TritonInfer._np()

        if arr.dtype == object:  # BYTES
            flat = [v.decode("utf-8") if isinstance(v, bytes) else v for v in arr.flat]
            return flat[0] if len(flat) == 1 else flat

        if arr.dtype == np.float16:  # FP16 → FP32
            arr = arr.astype(np.float32)

        return arr.tolist()

    @staticmethod
    def decode_response(result) -> dict:
        """Decode all outputs from an HTTP infer result into {output_name: decoded_value}."""
        response = result.get_response()
        return {o["name"]: TritonInfer.decode_output(result, o["name"]) for o in response.get("outputs", [])}

    # -------------------------------------------- #
    #          gRPC STREAMING  (LLM)               #
    # -------------------------------------------- #
    def stream(
        self,
        grpc_client,
        model_name: str,
        inputs: list,
        on_chunk: callable,
        output_name: str = "output",
        timeout: int = STREAM_TIMEOUT,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """
        Stream LLM inference via gRPC. Blocks until the stream ends or times out.

        on_chunk(text: str) is called for each decoded token.
        Stream end is detected when result.as_numpy() raises (Triton sends
        an empty final response that cannot be decoded).

        Raises TritonInferenceFailed on connection, stream error, or timeout.
        """
        done = threading.Event()
        errors = []
        started = False
        received_any = False

        def _callback(result, error):
            if error:
                observe_grpc_stream_failure("callback_error")
                errors.append(str(error))
                done.set()
                return
            try:
                piece = result.as_numpy(output_name)[0].decode("utf-8")
                on_chunk(piece)
                nonlocal received_any
                received_any = True
            except Exception as e:
                # Some clients signal "end of stream" by raising when outputs disappear.
                # If we've already received at least one chunk, treat this as a clean end.
                if received_any:
                    done.set()
                    return
                observe_grpc_stream_failure("decode_error")
                msg = f"STREAM_DECODE_ERROR: output_name={output_name!r} error={e}"
                logger.warning(msg)
                errors.append(msg)
                done.set()

        try:
            grpc_inputs = self._build_grpc_inputs(inputs)
            grpc_client.start_stream(callback=_callback)
            started = True
            grpc_client.async_stream_infer(model_name=model_name, inputs=grpc_inputs)

            deadline = time.time() + float(timeout)
            # Poll in small increments so we can react to cancellation signals quickly.
            while not done.is_set():
                if cancel_event is not None and cancel_event.is_set():
                    observe_grpc_stream_failure("client_cancel")
                    raise TritonInferenceFailed(model_name, "Stream aborted: client disconnected")
                remaining = deadline - time.time()
                if remaining <= 0:
                    observe_grpc_stream_failure("timeout")
                    raise TritonInferenceFailed(model_name, f"Stream timed out after {timeout}s")
                done.wait(timeout=min(0.05, remaining))
        except TritonError:
            raise
        except Exception as e:
            raise TritonInferenceFailed(model_name, str(e))
        finally:
            if started:
                try:
                    grpc_client.stop_stream()
                except Exception as e:
                    logger.warning("Failed to stop gRPC stream cleanly: %s", e)

        if errors:
            raise TritonInferenceFailed(model_name, errors[0])

    # -------------------------------------------- #
    #           HTTP SINGLE-SHOT  (ML)             #
    # -------------------------------------------- #
    def infer(self, http_client, model_name: str, inputs: list, timeout: int = 30):
        """
        Single-shot ML inference via HTTP. Returns the raw result object.
        Call TritonInfer.decode_response(result) to get decoded outputs.

        Raises TritonInferenceFailed on HTTP or connection error.
        """
        try:
            http_inputs = self._build_http_inputs(inputs)
            return http_client.infer(model_name=model_name, inputs=http_inputs, timeout=timeout)
        except TritonError:
            raise
        except Exception as e:
            raise TritonInferenceFailed(model_name, str(e))

    # -------------------------------------------- #
    #      HTTP SHM (ZERO-COPY)  — SCAFFOLDING     #
    # -------------------------------------------- #
    def infer_shm(self, http_client, model_name: str, shm_inputs, timeout: int = 30):
        """
        Placeholder for POSIX System Shared Memory integration.

        Contract:
        - `shm_inputs` is a list of SHMReference objects (metadata only).
        - The manager must not materialize numpy arrays for this path.

        Future implementation will register shared memory regions via
        tritonclient's System Shared Memory APIs and issue infer calls referencing them.
        """
        return self._infer_shm(http_client, model_name, shm_inputs, timeout=timeout)

    def _infer_shm(self, http_client, model_name: str, shm_inputs, *, timeout: int = 30):
        # Validate environment support early (contract: POSIX /dev/shm only for now).
        if not (os.path.isdir(SHM_ROOT) and os.access(SHM_ROOT, os.R_OK | os.W_OK | os.X_OK)):
            raise TritonSHMUnavailable(model_name, f"POSIX shared memory is not available ({SHM_ROOT} inaccessible)")

        if not isinstance(shm_inputs, list) or not shm_inputs:
            raise TritonSHMUnavailable(model_name, "Invalid SHM inputs: expected non-empty list")

        httpclient_mod = TritonInfer._httpclient()
        http_inputs: list[Any] = []

        # Ensure all regions are registered (LRU cached) and build InferInput objects
        for ref in shm_inputs:
            # SHMReference is defined in inference_orchestrator.py; we keep this duck-typed
            # to avoid import cycles. Required fields: name, shm_key, offset, byte_size, shape, dtype.
            try:
                inp_name = str(getattr(ref, "name"))
                shm_key = str(getattr(ref, "shm_key"))
                offset = int(getattr(ref, "offset"))
                byte_size = int(getattr(ref, "byte_size"))
                shape = list(getattr(ref, "shape"))
                dtype = str(getattr(ref, "dtype"))
            except Exception as exc:  # noqa: BLE001
                raise TritonSHMUnavailable(model_name, f"Invalid SHMReference object: {exc}", cause=exc)

            if not inp_name.strip():
                raise TritonSHMUnavailable(model_name, "SHMReference missing input name")
            if not shm_key.strip():
                raise TritonSHMUnavailable(model_name, "SHMReference missing shm_key")
            if offset < 0:
                raise TritonSHMUnavailable(model_name, "SHMReference offset must be >= 0")
            if byte_size <= 0:
                raise TritonSHMUnavailable(model_name, "SHMReference byte_size must be > 0")
            if any((not isinstance(d, int) or d < 0) for d in shape):
                raise TritonSHMUnavailable(model_name, "SHMReference shape must be list[int>=0]")

            # Fail-fast if key doesn't exist on disk (POSIX shm segments appear under /dev/shm).
            key_fs = shm_key[1:] if shm_key.startswith("/") else shm_key
            if not os.path.exists(os.path.join(SHM_ROOT, key_fs)):
                raise TritonSHMUnavailable(model_name, f"Shared memory key not found: {shm_key!r}")

            region_name = self._shm.ensure_registered(
                http_client=http_client,
                shm_key=shm_key,
                byte_size=byte_size,
                model_name=model_name,
            )

            datatype = TYPE_MAP.get(dtype, dtype)
            infer_input = httpclient_mod.InferInput(inp_name, shape, datatype)

            # Newer tritonclient supports offset; fall back gracefully.
            try:
                infer_input.set_shared_memory(region_name, byte_size, offset=offset)
            except TypeError:
                # Offset not supported by this client version; require offset=0.
                if offset != 0:
                    raise TritonSHMRegistrationFailed(
                        model_name,
                        "Client does not support shared-memory offsets; offset must be 0",
                    )
                infer_input.set_shared_memory(region_name, byte_size)

            http_inputs.append(infer_input)

        try:
            return http_client.infer(model_name=model_name, inputs=http_inputs, timeout=timeout)
        except TritonError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TritonInferenceFailed(model_name, f"SHM infer call failed: {exc}")


@dataclass(frozen=True)
class _RegisteredRegion:
    name: str
    shm_key: str
    byte_size: int
    handle: Any


class TritonSHMManager:
    """
    Thread-safe LRU cache of Triton system shared memory registrations per client.

    Purpose:
    - avoid redundant register/unregister calls for frequently reused shm_key regions
    - prevent leaks by capping number of active registrations per Triton client
    """

    def __init__(self, *, max_regions_per_client: int = 256) -> None:
        self._max = int(max_regions_per_client)
        self._lock = threading.RLock()
        # client_id -> OrderedDict[(shm_key, byte_size) -> _RegisteredRegion]
        self._lru: dict[int, OrderedDict[tuple[str, int], _RegisteredRegion]] = {}

    def ensure_registered(self, *, http_client: Any, shm_key: str, byte_size: int, model_name: str) -> str:
        client_id = id(http_client)
        key = (str(shm_key), int(byte_size))
        with self._lock:
            od = self._lru.setdefault(client_id, OrderedDict())
            existing = od.get(key)
            if existing is not None:
                od.move_to_end(key)
                return existing.name

            # Create a unique region name derived from client_id + key (stable, compact).
            region_name = f"tcm_shm_{client_id:x}_{abs(hash(key)) & 0xFFFFFFFF:x}"

            try:
                handle = shm.create_shared_memory_region(region_name, shm_key, int(byte_size))
            except Exception as exc:  # noqa: BLE001
                raise TritonSHMUnavailable(model_name, f"Failed to map shared memory region: {exc}", cause=exc)

            try:
                http_client.register_system_shared_memory(region_name, shm_key, int(byte_size))
            except Exception as exc:  # noqa: BLE001
                # Cleanup local handle if Triton registration fails.
                with contextlib.suppress(Exception):
                    shm.destroy_shared_memory_region(handle)
                raise TritonSHMRegistrationFailed(model_name, f"register_system_shared_memory failed: {exc}", cause=exc)

            entry = _RegisteredRegion(name=region_name, shm_key=shm_key, byte_size=int(byte_size), handle=handle)
            od[key] = entry
            od.move_to_end(key)

            # Evict LRU entries if over capacity.
            while self._max > 0 and len(od) > self._max:
                _, victim = od.popitem(last=False)
                self._unregister_best_effort(http_client=http_client, region=victim)

            return region_name

    def _unregister_best_effort(self, *, http_client: Any, region: _RegisteredRegion) -> None:
        with contextlib.suppress(Exception):
            http_client.unregister_system_shared_memory(region.name)
        with contextlib.suppress(Exception):
            shm.destroy_shared_memory_region(region.handle)
