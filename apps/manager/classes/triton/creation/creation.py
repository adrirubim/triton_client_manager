import logging
import time

import boto3
import tritonclient.http as httpclient
from pydantic import ValidationError
from src.Domains.Config.Schemas.RuntimeMinioPayload import RuntimeMinioPayload

from ..constants import GRPC_PORT, HTTP_PORT
from ..info.data.server import TritonServer
from ..tritonerrors import (
    TritonConfigDownloadFailed,
    TritonModelLoadFailed,
    TritonModelNotReady,
    TritonServerHealthFailed,
)

logger = logging.getLogger(__name__)

###################################
#       Triton Creation           #
###################################


class TritonCreation:
    """Handles the full lifecycle of bringing a new Triton server online."""

    def __init__(self, config: dict):
        self.client_request_timeout = config.get("client_request_timeout", 10)
        self.server_ready_timeout = config.get("server_ready_timeout", 60)
        self.model_ready_timeout = config.get("model_ready_timeout", 120)

    @staticmethod
    def _json_dumps(obj) -> str:
        import json

        return json.dumps(obj, separators=(",", ":"))

    @staticmethod
    def _boto3_client(minio_config: dict):
        return boto3.client(
            "s3",
            endpoint_url=minio_config["endpoint"],
            aws_access_key_id=minio_config["access_key"],
            aws_secret_access_key=minio_config["secret_key"],
        )

    @staticmethod
    def _grpcclient():
        import tritonclient.grpc as grpcclient  # heavy import (lazy)

        return grpcclient

    @staticmethod
    def _httpclient():
        return httpclient

    @staticmethod
    def _protobuf_tools():
        from google.protobuf import json_format, text_format  # heavy import (lazy)

        return json_format, text_format

    def handle(self, vm_id: str, vm_ip: str, minio: dict, triton: dict, container_id: str) -> TritonServer:
        # --- Extrapolate config.pbtxt ---
        config_json, inputs, outputs, model_name, port = self._process_config(minio_config=minio, triton_params=triton)
        # --- Check ---
        if not model_name:
            raise TritonModelLoadFailed("unknown", "Could not determine model name from config.pbtxt")
        if not inputs:
            raise TritonModelLoadFailed(model_name, "config.pbtxt has no inputs")
        if not outputs:
            raise TritonModelLoadFailed(model_name, "config.pbtxt has no outputs")

        # --- Single client based on port ---
        if port == GRPC_PORT:
            grpcclient = self._grpcclient()
            client = grpcclient.InferenceServerClient(url=f"{vm_ip}:{GRPC_PORT}")
            protocol = "grpc"
        else:
            httpclient = self._httpclient()
            client = httpclient.InferenceServerClient(url=f"{vm_ip}:{HTTP_PORT}")
            protocol = "http"

        # --- Wait server ready ---
        start = time.time()
        while (time.time() - start) < self.server_ready_timeout:
            time.sleep(1)
            if client.is_server_ready(client_timeout=self.client_request_timeout):
                break
        else:
            raise TritonServerHealthFailed(self.server_ready_timeout)

        # --- Wait for request loading ---
        try:
            client.load_model(
                model_name,
                config=config_json,
                client_timeout=self.client_request_timeout,
            )
        except Exception:
            raise TritonModelLoadFailed(model_name, "Load request failed")

        # --- Wait for model to be loaded ---
        start = time.time()
        while (time.time() - start) < self.model_ready_timeout:
            time.sleep(1)
            if client.is_model_ready(model_name, client_timeout=self.client_request_timeout):
                break
        else:
            raise TritonModelNotReady(model_name, self.model_ready_timeout)

        # --- Create Server ---
        server = TritonServer(
            vm_id=vm_id,
            vm_ip=vm_ip,
            status="ready",
            container_id=container_id,
            client=client,
            model_name=model_name,
            inputs=inputs,
            outputs=outputs,
            protocol=protocol,
        )

        logger.info(f" Server ({vm_ip}, {container_id[:12]}) ready — model='{model_name}'")

        return server

    # -------------------------------------------- #
    #           Model Config helpers               #
    # -------------------------------------------- #

    def _download_pbtxt(self, key: str, minio_config: dict) -> str:
        try:
            s3 = self._boto3_client(minio_config)
            obj = s3.get_object(Bucket=minio_config["bucket"], Key=key)
            return obj["Body"].read().decode("utf-8")
        except Exception as e:
            raise TritonConfigDownloadFailed(str(e))

    def _pbtxt_to_config(self, parameters: dict, pbtxt_content: str) -> tuple:
        """Parse pbtxt, apply parameters, return (compact JSON string, inputs, outputs, model_name, port)."""
        grpcclient = self._grpcclient()
        json_format, text_format = self._protobuf_tools()

        cfg = grpcclient.model_config_pb2.ModelConfig()
        text_format.Parse(pbtxt_content, cfg)

        for key, value in parameters.items():
            cfg.parameters[key].string_value = str(value)

        kwargs = dict(preserving_proto_field_name=True, use_integers_for_enums=False)
        try:
            cfg_dict = json_format.MessageToDict(cfg, including_default_value_fields=False, **kwargs)
        except TypeError:
            cfg_dict = json_format.MessageToDict(cfg, **kwargs)

        # protobuf int64 dims come out as strings from MessageToDict — convert back
        def _schema(entries):
            return [
                {
                    "name": e.get("name"),
                    "type": e.get("data_type"),
                    "dims": [int(d) for d in e.get("dims", [])],
                }
                for e in entries
            ]

        inputs = _schema(cfg_dict.get("input", []))
        outputs = _schema(cfg_dict.get("output", []))
        model_name = cfg_dict.get("name", "")

        decoupled = cfg_dict.get("model_transaction_policy", {}).get("decoupled", False)
        port = GRPC_PORT if decoupled else HTTP_PORT

        config_json = self._json_dumps(cfg_dict)
        return config_json, inputs, outputs, model_name, port

    def _process_config(self, minio_config: dict, triton_params: dict) -> tuple:
        """
        Downloads config.pbtxt from MinIO S3, extracts the input schema, and optionally
        builds the JSON config string for the Triton load request.
        """
        try:
            minio_runtime = RuntimeMinioPayload.model_validate(minio_config or {})
        except ValidationError as exc:
            raise TritonConfigDownloadFailed(f"Invalid MinIO payload (runtime): {exc}") from exc

        folder = minio_runtime.folder
        key = f"{folder}/{folder.rstrip('/').split('/')[-1]}/config.pbtxt"

        logger.info(f" Downloading config from {minio_runtime.endpoint}/{minio_runtime.bucket}/{key}")
        pbtxt = self._download_pbtxt(key, minio_config)

        config_json, inputs, outputs, model_name, port = self._pbtxt_to_config(triton_params, pbtxt)

        if not triton_params:
            config_json = None

        return config_json, inputs, outputs, model_name, port
