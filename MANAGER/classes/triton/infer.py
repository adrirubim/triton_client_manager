import threading

import numpy as np
import tritonclient.grpc as grpcclient
import tritonclient.http as httpclient

from .constants import TYPE_MAP
from .tritonerrors import TritonInferenceFailed

###################################
#      Triton Inference Runner    #
###################################

STREAM_TIMEOUT = 120  # seconds before a hung gRPC stream is abandoned


class TritonInfer:
    """Sends inference requests to Triton — gRPC streaming (LLM) or HTTP (ML)."""

    # -------------------------------------------- #
    #               INPUT BUILDERS                  #
    # -------------------------------------------- #
    @staticmethod
    def _build_grpc_inputs(inputs: list) -> list:
        """Convert payload inputs to tritonclient.grpc InferInput objects."""
        grpc_inputs = []
        for inp in inputs:
            dims = inp["dims"]
            shape = [dims] if isinstance(dims, int) else list(dims)
            datatype = TYPE_MAP.get(inp["type"], inp["type"])
            value = inp["value"]

            infer_input = grpcclient.InferInput(inp["name"], shape, datatype)

            if datatype == "BYTES":
                data = np.array(
                    [value.encode("utf-8") if isinstance(value, str) else value],
                    dtype=object,
                )
            else:
                data = np.array([value])

            infer_input.set_data_from_numpy(data)
            grpc_inputs.append(infer_input)

        return grpc_inputs

    @staticmethod
    def _build_http_inputs(inputs: list) -> list:
        """Convert payload inputs to tritonclient.http InferInput objects."""
        http_inputs = []
        for inp in inputs:
            dims = inp["dims"]
            shape = [dims] if isinstance(dims, int) else list(dims)
            datatype = TYPE_MAP.get(inp["type"], inp["type"])
            value = inp["value"]

            infer_input = httpclient.InferInput(inp["name"], shape, datatype)

            if datatype == "BYTES":
                data = np.array(
                    [value.encode("utf-8") if isinstance(value, str) else value],
                    dtype=object,
                )
            else:
                data = np.array([value])

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
        return {
            o["name"]: TritonInfer.decode_output(result, o["name"])
            for o in response.get("outputs", [])
        }

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

        def _callback(result, error):
            if error:
                errors.append(str(error))
                done.set()
                return
            try:
                piece = result.as_numpy(output_name)[0].decode("utf-8")
                on_chunk(piece)
            except Exception:
                done.set()  # stream finished (final undecodable response)

        try:
            grpc_inputs = self._build_grpc_inputs(inputs)

            grpc_client.start_stream(callback=_callback)
            grpc_client.async_stream_infer(model_name=model_name, inputs=grpc_inputs)

            if not done.wait(timeout=timeout):
                raise TritonInferenceFailed(
                    model_name, f"Stream timed out after {timeout}s"
                )

            grpc_client.stop_stream()

        except TritonInferenceFailed:
            raise
        except Exception as e:
            raise TritonInferenceFailed(model_name, str(e))

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
            return http_client.infer(
                model_name=model_name, inputs=http_inputs, client_timeout=timeout
            )
        except Exception as e:
            raise TritonInferenceFailed(model_name, str(e))
