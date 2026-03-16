import os
from urllib.parse import urlparse

import boto3
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
        region = os.getenv("AWS_REGION") or os.getenv("MINIO_REGION") or "us-east-1"
        secure = (os.getenv("TCM_S3_SECURE", "true").strip().lower() in {"1","true","yes","on"})
        session = boto3.session.Session(region_name=region)
        self.s3 = session.client("s3", endpoint_url=endpoint, use_ssl=secure)

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
