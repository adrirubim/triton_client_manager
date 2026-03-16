from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class TritonModelIO(BaseModel):
    """Entrada/salida de modelo Triton para config.pbtxt."""

    name: str
    data_type: str
    dims: List[int] = Field(default_factory=list)


class TritonModelConfig(BaseModel):
    """Esquema simplificado para generar `config.pbtxt`."""

    name: str
    platform: str
    max_batch_size: int = 0
    inputs: List[TritonModelIO] = Field(default_factory=list)
    outputs: List[TritonModelIO] = Field(default_factory=list)
