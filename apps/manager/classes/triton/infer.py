import logging
import threading

from utils.metrics import observe_grpc_stream_failure

from .constants import TYPE_MAP
from .tritonerrors import TritonInferenceFailed

logger = logging.getLogger(__name__)

###################################
#      Triton Inference Runner    #
###################################

STREAM_TIMEOUT = 120  # seconds before a hung gRPC stream is abandoned


class TritonInfer:
    """Sends inference requests to Triton — gRPC streaming (LLM) or HTTP (ML)."""

    @staticmethod
    def _np():
        import numpy as np  # heavy import (lazy)

        return np

    @staticmethod
    def _grpcclient():
        import tritonclient.grpc as grpcclient  # heavy import (lazy)

        return grpcclient

    @staticmethod
    def _httpclient():
        import tritonclient.http as httpclient  # heavy import (lazy)

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

        dtype_map = {
            "BOOL": np.bool_,
            "INT8": np.int8,
            "INT16": np.int16,
            "INT32": np.int32,
            "INT64": np.int64,
            "UINT8": np.uint8,
            "UINT16": np.uint16,
            "UINT32": np.uint32,
            "UINT64": np.uint64,
            "FP16": np.float16,
            "FP32": np.float32,
            "FP64": np.float64,
        }
        np_dtype = dtype_map.get(datatype)

        if isinstance(value, (list, tuple, np.ndarray)):
            return np.asarray(value, dtype=np_dtype) if np_dtype is not None else np.asarray(value)
        return np.asarray([value], dtype=np_dtype) if np_dtype is not None else np.asarray([value])

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

            if not done.wait(timeout=timeout):
                observe_grpc_stream_failure("timeout")
                raise TritonInferenceFailed(model_name, f"Stream timed out after {timeout}s")
        except TritonInferenceFailed:
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
        except Exception as e:
            raise TritonInferenceFailed(model_name, str(e))
