from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ModelCategory(str, Enum):
    llm = "LLM"
    ml = "ML"


class ModelFormat(str, Enum):
    onnx = "onnx"
    safetensors = "safetensors"
    gguf = "gguf"
    pytorch = "pytorch"


class ModelIO(BaseModel):
    name: str
    dtype: str
    shape: List[int] = Field(default_factory=list)


class ModelAnalysisReport(BaseModel):
    name: str
    category: ModelCategory
    format: ModelFormat
    miniopath: str
    local_path: str
    size_bytes: int
    size_gb: float
    inputs: List[ModelIO] = Field(default_factory=list)
    outputs: List[ModelIO] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

