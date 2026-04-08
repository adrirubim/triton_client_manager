import os
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
        secure = os.getenv("TCM_S3_SECURE", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
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
                responses.append(
                    pb_utils.InferenceResponse(
                        error=pb_utils.TritonError("Missing MINIO_URL or BYTES")
                    )
                )
                continue
            uri = url_t.as_numpy().item().decode("utf-8")
            try:
                bucket, key = _parse_s3(uri)
                raw = bytes(bytes_t.as_numpy().astype(np.uint8).tobytes())
                self.s3.put_object(Bucket=bucket, Key=key, Body=raw)
                out = pb_utils.Tensor(
                    "OUT_URL", np.array([uri.encode("utf-8")], dtype=object)
                )
                responses.append(pb_utils.InferenceResponse(output_tensors=[out]))
            except Exception as e:
                responses.append(
                    pb_utils.InferenceResponse(error=pb_utils.TritonError(str(e)))
                )
        return responses
