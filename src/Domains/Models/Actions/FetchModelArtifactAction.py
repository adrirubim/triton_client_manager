from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import boto3

logger = logging.getLogger(__name__)

_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _validate_model_name(name: str) -> str:
    if not isinstance(name, str) or not name or not _MODEL_NAME_RE.fullmatch(name):
        raise ValueError(
            "Invalid model name. Expected ^[a-zA-Z0-9._-]+$ (no slashes, no traversal)."
        )
    return name


def _ensure_within_root(path: Path, root: Path) -> Path:
    root_r = root.resolve()
    path_r = path.resolve()
    try:
        path_r.relative_to(root_r)
    except Exception as exc:
        raise ValueError(f"Refusing path outside sandbox root: {path_r}") from exc
    return path_r


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
    cache_size_warning_bytes: int = 10 * 1024 * 1024 * 1024  # 10 GB

    def _cache_total_size_bytes(self, root: Path) -> int:
        total = 0
        if not root.exists():
            return 0
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                p = Path(dirpath) / name
                try:
                    total += p.stat().st_size
                except Exception:
                    continue
        return total

    def run(self) -> FetchedArtifact:
        _validate_model_name(self.name)

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

        cache_root = Path(self.cache_root)
        dst_dir = cache_root / self.name
        # Ensure target stays within cache_root even if name is malicious.
        _ensure_within_root(dst_dir, cache_root)
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst_path = dst_dir / Path(key).name
        tmp_path = dst_path.with_name(dst_path.name + ".tmp")

        # Best-effort cache hygiene warning (manual cleanup prompt).
        try:
            cache_root = Path(self.cache_root)
            total = self._cache_total_size_bytes(cache_root)
            if total > int(self.cache_size_warning_bytes):
                logger.warning(
                    "STALE_CACHE_WARNING: model cache size is %d bytes (> %d). Consider cleanup/GC of %s",
                    total,
                    int(self.cache_size_warning_bytes),
                    str(cache_root),
                )
        except Exception:
            pass

        # Prefer HEAD to get size before download
        size: Optional[int] = None
        try:
            head = client.head_object(Bucket=bucket, Key=key)
            if isinstance(head, dict) and "ContentLength" in head:
                size = int(head["ContentLength"])
        except Exception:
            size = None
        # Atomic download: write to a temp path, then replace.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
            client.download_file(bucket, key, str(tmp_path))
            os.replace(str(tmp_path), str(dst_path))
        finally:
            # Best-effort cleanup if something failed mid-download.
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

        stat_size = dst_path.stat().st_size
        if size is None:
            size = stat_size

        return FetchedArtifact(
            miniopath=self.miniopath,
            local_path=str(dst_path),
            size_bytes=size,
        )
