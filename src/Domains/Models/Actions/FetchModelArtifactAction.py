from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import boto3


@dataclass(frozen=True)
class FetchedArtifact:
    miniopath: str
    local_path: str
    size_bytes: int

    @property
    def size_gb(self) -> float:
        return self.size_bytes / (1024**3)


def _parse_s3_uri(uri: str) -> Tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise ValueError(f"miniopath must be s3://... or a local path, got: {uri!r}")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        raise ValueError(f"Invalid s3 URI (expected s3://bucket/key): {uri!r}")
    return bucket, key


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class FetchModelArtifactAction:
    """
    Download a model artifact from `miniopath` (s3://...) to a cached local path.

    Supports MinIO/S3 via boto3. Configuration via environment variables:
    - TCM_S3_ENDPOINT (optional, for MinIO)
    - AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (required for private MinIO/S3)
    - AWS_REGION or MINIO_REGION (optional)
    - TCM_S3_SECURE=true|false (default true)
    """

    miniopath: str
    name: str
    cache_root: str = ".cache/models"

    def run(self) -> FetchedArtifact:
        # Local path passthrough
        if not self.miniopath.startswith("s3://"):
            p = Path(self.miniopath)
            if not p.is_file():
                raise FileNotFoundError(f"Model file not found: {p}")
            return FetchedArtifact(
                miniopath=self.miniopath,
                local_path=str(p),
                size_bytes=p.stat().st_size,
            )

        bucket, key = _parse_s3_uri(self.miniopath)

        endpoint = os.getenv("TCM_S3_ENDPOINT")
        region = os.getenv("AWS_REGION") or os.getenv("MINIO_REGION") or "us-east-1"
        secure = _bool_env("TCM_S3_SECURE", True)

        session = boto3.session.Session(region_name=region)
        client = session.client(
            "s3",
            endpoint_url=endpoint,
            use_ssl=secure,
        )

        dst_dir = Path(self.cache_root) / self.name
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst_path = dst_dir / Path(key).name

        # Prefer HEAD to get size before download
        size: Optional[int] = None
        try:
            head = client.head_object(Bucket=bucket, Key=key)
            if isinstance(head, dict) and "ContentLength" in head:
                size = int(head["ContentLength"])
        except Exception:
            size = None

        client.download_file(bucket, key, str(dst_path))
        stat_size = dst_path.stat().st_size
        if size is None:
            size = stat_size

        return FetchedArtifact(
            miniopath=self.miniopath,
            local_path=str(dst_path),
            size_bytes=size,
        )

