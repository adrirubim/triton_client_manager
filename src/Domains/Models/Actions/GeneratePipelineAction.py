from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_MINIO_DOWNLOAD = "MINIO_DOWNLOAD_IMG_TO_BYTES"
_BYTES_TO_UINT8 = "BYTES_TO_UINT8"
_MINIO_UPLOAD = "MINIO_UPLOAD_IMG_BYTES"


def _write_file(path: Path, content: str, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return
    path.write_text(content, encoding="utf-8")


def _ensure_python_model(
    repo_root: Path, name: str, config_pbtxt: str, model_py: str, overwrite: bool
) -> None:
    model_root = repo_root / "infra" / "models" / name
    weights_dir = model_root / "1" / "weights"
    utils_dir = model_root / "1" / "utils"
    os.makedirs(weights_dir, exist_ok=True)
    os.makedirs(utils_dir, exist_ok=True)
    _write_file(model_root / "config.pbtxt", config_pbtxt, overwrite=overwrite)
    _write_file(model_root / "1" / "model.py", model_py, overwrite=overwrite)
    _write_file(
        utils_dir / "timeit.py",
        "import time\n\n\ndef time_it(fn):\n    def wrapper(*args, **kwargs):\n        start = time.perf_counter()\n        out = fn(*args, **kwargs)\n        return out, time.perf_counter() - start\n\n    return wrapper\n",
        overwrite=overwrite,
    )


def _minio_download_config() -> str:
    return "\n".join(
        [
            f'name: "{_MINIO_DOWNLOAD}"',
            'backend: "python"',
            "max_batch_size: 0",
            "input [",
            '  { name: "MINIO_URL" data_type: TYPE_STRING dims: [ 1 ] }',
            "]",
            "output [",
            '  { name: "BYTES" data_type: TYPE_UINT8 dims: [ -1 ] }',
            "]",
            "",
        ]
    )


def _minio_download_model_py() -> str:
    return """import os
from urllib.parse import urlparse

import boto3
from botocore.config import Config
import numpy as np
import triton_python_backend_utils as pb_utils


def _parse_s3(uri: str) -> tuple[str, str]:
    p = urlparse(uri)
    if p.scheme != "s3":
        raise ValueError(f"expected s3://bucket/key, got {uri!r}")
    return p.netloc, p.path.lstrip("/")


class TritonPythonModel:
    def initialize(self, args):
        endpoint = os.getenv("TCM_S3_ENDPOINT")
        if not endpoint:
            raise ValueError("TCM_S3_ENDPOINT must be set (MinIO/S3 endpoint URL)")
        region = os.getenv("AWS_REGION") or os.getenv("MINIO_REGION") or "us-east-1"
        secure = (os.getenv("TCM_S3_SECURE", "true").strip().lower() in {"1","true","yes","on"})
        connect_timeout_s = float(os.getenv("TCM_S3_CONNECT_TIMEOUT_SECONDS", "5.0"))
        read_timeout_s = float(os.getenv("TCM_S3_READ_TIMEOUT_SECONDS", "30.0"))
        boto_cfg = Config(
            connect_timeout=connect_timeout_s,
            read_timeout=read_timeout_s,
            retries={"max_attempts": 3, "mode": "standard"},
        )
        session = boto3.session.Session(region_name=region)
        self.s3 = session.client(
            "s3",
            endpoint_url=endpoint,
            use_ssl=secure,
            config=boto_cfg,
        )

    def execute(self, requests):
        responses = []
        for req in requests:
            url_t = pb_utils.get_input_tensor_by_name(req, "MINIO_URL")
            if url_t is None:
                responses.append(pb_utils.InferenceResponse(error=pb_utils.TritonError("Missing MINIO_URL")))
                continue
            uri = url_t.as_numpy().item().decode("utf-8")
            try:
                bucket, key = _parse_s3(uri)
                obj = self.s3.get_object(Bucket=bucket, Key=key)
                data = obj["Body"].read()
                out = pb_utils.Tensor("BYTES", np.frombuffer(data, dtype=np.uint8))
                responses.append(pb_utils.InferenceResponse(output_tensors=[out]))
            except Exception as e:
                responses.append(pb_utils.InferenceResponse(error=pb_utils.TritonError(str(e))))
        return responses
"""


def _bytes_to_uint8_config() -> str:
    return "\n".join(
        [
            f'name: "{_BYTES_TO_UINT8}"',
            'backend: "python"',
            "max_batch_size: 0",
            "input [",
            '  { name: "BYTES" data_type: TYPE_UINT8 dims: [ -1 ] }',
            '  { name: "IMG_SIZE" data_type: TYPE_INT32 dims: [ 2 ] }',
            "]",
            "output [",
            '  { name: "IMG_UINT8" data_type: TYPE_UINT8 dims: [ 3, -1, -1 ] }',
            '  { name: "IMG_ORIGINAL" data_type: TYPE_UINT8 dims: [ -1 ] }',
            "]",
            "",
        ]
    )


def _bytes_to_uint8_model_py() -> str:
    return """import io

import numpy as np
import triton_python_backend_utils as pb_utils
from PIL import Image


class TritonPythonModel:
    def initialize(self, args):
        pass

    def execute(self, requests):
        responses = []
        for req in requests:
            bytes_t = pb_utils.get_input_tensor_by_name(req, "BYTES")
            size_t = pb_utils.get_input_tensor_by_name(req, "IMG_SIZE")
            if bytes_t is None or size_t is None:
                responses.append(pb_utils.InferenceResponse(error=pb_utils.TritonError("Missing BYTES or IMG_SIZE")))
                continue
            try:
                size = size_t.as_numpy().astype(np.int32).reshape(-1)
                if size.size != 2:
                    raise ValueError("IMG_SIZE must be a 2-element int32 tensor: [H, W]")
                h = int(size[0])
                w = int(size[1])
                if h <= 0 or w <= 0:
                    raise ValueError("IMG_SIZE values must be > 0")

                raw = bytes(bytes_t.as_numpy().astype(np.uint8).tobytes())
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                img = img.resize((w, h))  # PIL uses (W, H)
                arr = np.asarray(img, dtype=np.uint8)  # HWC
                arr = np.transpose(arr, (2, 0, 1))     # CHW
                out1 = pb_utils.Tensor("IMG_UINT8", arr)
                out2 = pb_utils.Tensor("IMG_ORIGINAL", np.frombuffer(raw, dtype=np.uint8))
                responses.append(pb_utils.InferenceResponse(output_tensors=[out1, out2]))
            except Exception as e:
                responses.append(pb_utils.InferenceResponse(error=pb_utils.TritonError(str(e))))
        return responses
"""


def _minio_upload_config() -> str:
    return "\n".join(
        [
            f'name: "{_MINIO_UPLOAD}"',
            'backend: "python"',
            "max_batch_size: 0",
            "input [",
            '  { name: "MINIO_URL" data_type: TYPE_STRING dims: [ 1 ] }',
            '  { name: "BYTES" data_type: TYPE_UINT8 dims: [ -1 ] }',
            "]",
            "output [",
            '  { name: "OUT_URL" data_type: TYPE_STRING dims: [ 1 ] }',
            "]",
            "",
        ]
    )


def _minio_upload_model_py() -> str:
    return """import os
from urllib.parse import urlparse

import boto3
from botocore.config import Config
import numpy as np
import triton_python_backend_utils as pb_utils


def _parse_s3(uri: str) -> tuple[str, str]:
    p = urlparse(uri)
    if p.scheme != "s3":
        raise ValueError(f"expected s3://bucket/key, got {uri!r}")
    return p.netloc, p.path.lstrip("/")


class TritonPythonModel:
    def initialize(self, args):
        endpoint = os.getenv("TCM_S3_ENDPOINT")
        if not endpoint:
            raise ValueError("TCM_S3_ENDPOINT must be set (MinIO/S3 endpoint URL)")
        region = os.getenv("AWS_REGION") or os.getenv("MINIO_REGION") or "us-east-1"
        secure = (os.getenv("TCM_S3_SECURE", "true").strip().lower() in {"1","true","yes","on"})
        connect_timeout_s = float(os.getenv("TCM_S3_CONNECT_TIMEOUT_SECONDS", "5.0"))
        read_timeout_s = float(os.getenv("TCM_S3_READ_TIMEOUT_SECONDS", "30.0"))
        boto_cfg = Config(
            connect_timeout=connect_timeout_s,
            read_timeout=read_timeout_s,
            retries={"max_attempts": 3, "mode": "standard"},
        )
        session = boto3.session.Session(region_name=region)
        self.s3 = session.client(
            "s3",
            endpoint_url=endpoint,
            use_ssl=secure,
            config=boto_cfg,
        )

    def execute(self, requests):
        responses = []
        for req in requests:
            url_t = pb_utils.get_input_tensor_by_name(req, "MINIO_URL")
            bytes_t = pb_utils.get_input_tensor_by_name(req, "BYTES")
            if url_t is None or bytes_t is None:
                responses.append(pb_utils.InferenceResponse(error=pb_utils.TritonError("Missing MINIO_URL or BYTES")))
                continue
            uri = url_t.as_numpy().item().decode("utf-8")
            try:
                bucket, key = _parse_s3(uri)
                raw = bytes(bytes_t.as_numpy().astype(np.uint8).tobytes())
                self.s3.put_object(Bucket=bucket, Key=key, Body=raw)
                out = pb_utils.Tensor("OUT_URL", np.array([uri.encode(\"utf-8\")], dtype=object))
                responses.append(pb_utils.InferenceResponse(output_tensors=[out]))
            except Exception as e:
                responses.append(pb_utils.InferenceResponse(error=pb_utils.TritonError(str(e))))
        return responses
"""


@dataclass
class GeneratePipelineAction:
    repo_root: str
    name: str
    overwrite: bool = False

    def run(self) -> Path:
        repo = Path(self.repo_root)
        pipeline_name = f"{self.name}_PIPELINE"
        pipeline_root = repo / "infra" / "models" / pipeline_name
        pipeline_root.mkdir(parents=True, exist_ok=True)

        # Ensure step models exist (Python backend scaffolds)
        _ensure_python_model(
            repo,
            _MINIO_DOWNLOAD,
            _minio_download_config(),
            _minio_download_model_py(),
            self.overwrite,
        )
        _ensure_python_model(
            repo,
            _BYTES_TO_UINT8,
            _bytes_to_uint8_config(),
            _bytes_to_uint8_model_py(),
            self.overwrite,
        )
        _ensure_python_model(
            repo,
            _MINIO_UPLOAD,
            _minio_upload_config(),
            _minio_upload_model_py(),
            self.overwrite,
        )

        # Ensemble config (minimal): MINIO download -> bytes_to_uint8 -> model -> MINIO upload
        config = "\n".join(
            [
                f'name: "{pipeline_name}"',
                'platform: "ensemble"',
                "max_batch_size: 0",
                "",
                "input [",
                '  { name: "MINIO_URL" data_type: TYPE_STRING dims: [ 1 ] },',
                '  { name: "IMG_SIZE" data_type: TYPE_INT32 dims: [ 2 ] }',
                "]",
                "",
                "output [",
                '  { name: "OUT_URL" data_type: TYPE_STRING dims: [ 1 ] }',
                "]",
                "",
                "ensemble_scheduling {",
                "  step [",
                "    {",
                f'      model_name: "{_MINIO_DOWNLOAD}"',
                "      model_version: -1",
                '      input_map { key: "MINIO_URL" value: "MINIO_URL" }',
                '      output_map { key: "BYTES" value: "BYTES" }',
                "    },",
                "    {",
                f'      model_name: "{_BYTES_TO_UINT8}"',
                "      model_version: -1",
                '      input_map { key: "BYTES" value: "BYTES" }',
                '      input_map { key: "IMG_SIZE" value: "IMG_SIZE" }',
                '      output_map { key: "IMG_UINT8" value: "images" }',
                '      output_map { key: "IMG_ORIGINAL" value: "IMG_ORIGINAL" }',
                "    },",
                "    {",
                f'      model_name: "{self.name}"',
                "      model_version: -1",
                '      input_map { key: "INPUT__0" value: "images" }',
                '      output_map { key: "OUTPUT__0" value: "MODEL_OUT" }',
                "    },",
                "    {",
                f'      model_name: "{_MINIO_UPLOAD}"',
                "      model_version: -1",
                '      input_map { key: "MINIO_URL" value: "MINIO_URL" }',
                '      input_map { key: "BYTES" value: "IMG_ORIGINAL" }',
                '      output_map { key: "OUT_URL" value: "OUT_URL" }',
                "    }",
                "  ]",
                "}",
                "",
            ]
        )

        _write_file(pipeline_root / "config.pbtxt", config, overwrite=self.overwrite)
        return pipeline_root
