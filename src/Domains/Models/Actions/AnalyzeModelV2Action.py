from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.Domains.Models.Actions.FetchModelArtifactAction import FetchModelArtifactAction
from src.Domains.Models.Analysis.GgufInspector import GgufInspector
from src.Domains.Models.Analysis.OnnxInspector import OnnxInspector
from src.Domains.Models.Analysis.PyTorchInspector import PyTorchInspector
from src.Domains.Models.Analysis.SafetensorsInspector import SafetensorsInspector
from src.Domains.Models.Schemas.ModelAnalysisReport import (
    ModelAnalysisReport,
    ModelCategory,
    ModelFormat,
)


def _detect_format(path: str, explicit: str | None = None) -> ModelFormat:
    if explicit:
        return ModelFormat(explicit)
    suffix = Path(path).suffix.lower()
    if suffix == ".onnx":
        return ModelFormat.onnx
    if suffix == ".gguf":
        return ModelFormat.gguf
    if suffix in {".pt", ".pth"}:
        return ModelFormat.pytorch
    if suffix in {".safetensors"}:
        return ModelFormat.safetensors
    raise ValueError(f"Unsupported model format for analysis: {suffix!r}")


@dataclass
class AnalyzeModelV2Action:
    miniopath: str
    name: str
    category: ModelCategory
    format: str | None = None

    def run(self) -> ModelAnalysisReport:
        fetched = FetchModelArtifactAction(miniopath=self.miniopath, name=self.name).run()
        fmt = _detect_format(fetched.local_path, self.format)

        warnings: list[str] = []
        inputs = []
        outputs = []

        if fmt == ModelFormat.onnx:
            ins = OnnxInspector(model_path=fetched.local_path).run()
            inputs = ins.inputs
            outputs = ins.outputs
            if not inputs or not outputs:
                warnings.append("ONNX graph has empty inputs/outputs (possible invalid export).")
        elif fmt == ModelFormat.gguf:
            ins = GgufInspector(model_path=fetched.local_path).run()
            inputs = ins.inputs
            outputs = ins.outputs
            warnings.extend(ins.warnings)
        elif fmt == ModelFormat.pytorch:
            ins = PyTorchInspector(model_path=fetched.local_path).run()
            inputs = ins.inputs
            outputs = ins.outputs
            warnings.extend(ins.warnings)
            warnings.append(
                f"PyTorch ZIP weights size (uncompressed, recorded) ~{ins.total_uncompressed_size_recorded} bytes (members_recorded={ins.members_recorded}, member_count={ins.member_count})."
            )
        elif fmt == ModelFormat.safetensors:
            ins = SafetensorsInspector(model_path=fetched.local_path).run()
            # safetensors does not define an IO contract; report tensors as a flat list in `inputs`
            inputs = ins.tensors
            outputs = []
            warnings.append("safetensors does not define an inference IO contract; reporting tensors only.")
        else:
            raise ValueError(f"Unsupported format: {fmt}")

        # Basic safety heuristics
        if fmt == ModelFormat.onnx:
            warnings.append("ONNX is data-only, but always treat untrusted models as untrusted artifacts.")
        if fmt == ModelFormat.gguf:
            warnings.append(
                "GGUF inspection is KV-metadata only; weights are not loaded and deep tensor IO cannot be safely inferred."
            )
        if fmt == ModelFormat.pytorch:
            warnings.append(
                "PyTorch inspection is inspection-only for safety: no pickle, no extraction, no execution."
            )
        if fmt == ModelFormat.safetensors:
            warnings.append("safetensors is data-only; loading is generally safe, but inference wrapper may execute code.")

        return ModelAnalysisReport(
            name=self.name,
            category=self.category,
            format=fmt,
            miniopath=self.miniopath,
            local_path=fetched.local_path,
            size_bytes=fetched.size_bytes,
            size_gb=fetched.size_gb,
            inputs=inputs,
            outputs=outputs,
            warnings=warnings,
        )

