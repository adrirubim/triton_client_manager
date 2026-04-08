from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class TritonModelIO(BaseModel):
    """Triton model input/output entry for config.pbtxt."""

    name: str
    data_type: str
    dims: List[int] = Field(default_factory=list)


class TritonModelConfig(BaseModel):
    """Minimal schema used to generate a `config.pbtxt`."""

    name: str
    platform: str
    # When weights live under a subdirectory (e.g. 1/weights/model.onnx), Triton
    # needs this to find the actual model file.
    default_model_filename: str | None = None
    max_batch_size: int = 0
    inputs: List[TritonModelIO] = Field(default_factory=list)
    outputs: List[TritonModelIO] = Field(default_factory=list)


__all__ = ["TritonModelConfig", "TritonModelIO"]
