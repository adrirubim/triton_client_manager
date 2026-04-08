from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class RuntimeMinioPayload(BaseModel):
    """
    Runtime MinIO payload schema used by management actions.

    This is distinct from the manager's YAML config schema: runtime payloads
    must include endpoint + bucket + folder in addition to credentials.
    """

    endpoint: AnyHttpUrl
    bucket: str = Field(min_length=1)
    folder: str = Field(min_length=1)
    access_key: str = Field(min_length=1)
    secret_key: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


__all__ = ["RuntimeMinioPayload"]
