from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from src.Domains.Models.Schemas.ModelAnalysisReport import ModelFormat, ModelIO


class SupportedModality(str, Enum):
    text = "text"
    image = "image"
    audio = "audio"
    video = "video"


class IssueLevel(str, Enum):
    warning = "warning"
    error = "error"


class InspectionIssue(BaseModel):
    level: IssueLevel = IssueLevel.warning
    message: str
    code: Optional[str] = None
    source: Optional[str] = None


class ModelIOInfo(BaseModel):
    inputs: List[ModelIO] = Field(default_factory=list)
    outputs: List[ModelIO] = Field(default_factory=list)


class ModelInspectionResult(BaseModel):
    format: ModelFormat
    size_bytes: int
    io_info: ModelIOInfo = Field(default_factory=ModelIOInfo)
    supported_modalities: List[SupportedModality] = Field(default_factory=list)
    issues: List[InspectionIssue] = Field(default_factory=list)


class AnalyzeModelV2Payload(BaseModel):
    inspection: ModelInspectionResult
    triton_config_pbtxt: str

