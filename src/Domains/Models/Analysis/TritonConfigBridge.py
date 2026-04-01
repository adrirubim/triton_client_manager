from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from src.Domains.Models.Schemas.ModelAnalysisReport import ModelFormat, ModelIO
from src.Domains.Models.Schemas.ModelInspectionResult import (
    InspectionIssue,
    IssueLevel,
    ModelInspectionResult,
)


_TRITON_DTYPE_MAP = {
    "FP16": "TYPE_FP16",
    "FLOAT16": "TYPE_FP16",
    "FP32": "TYPE_FP32",
    "FLOAT32": "TYPE_FP32",
    "FP64": "TYPE_FP64",
    "FLOAT64": "TYPE_FP64",
    "INT8": "TYPE_INT8",
    "INT16": "TYPE_INT16",
    "INT32": "TYPE_INT32",
    "INT64": "TYPE_INT64",
    "UINT8": "TYPE_UINT8",
    "BOOL": "TYPE_BOOL",
    "BYTES": "TYPE_BYTES",
    "STRING": "TYPE_STRING",
}


def _dims_to_triton(dims: List[int], *, issues: List[InspectionIssue], tensor_name: str) -> List[int]:
    out: List[int] = []
    for d in dims:
        try:
            di = int(d)
        except Exception:
            di = -1
            issues.append(
                InspectionIssue(
                    level=IssueLevel.warning,
                    code="TRITON_DIM_COERCE",
                    source="TritonConfigBridge",
                    message=f"Tensor {tensor_name!r}: non-integer dim coerced to -1 for Triton.",
                )
            )
        if di <= 0:
            if di != -1:
                issues.append(
                    InspectionIssue(
                        level=IssueLevel.warning,
                        code="TRITON_DIM_NONPOSITIVE",
                        source="TritonConfigBridge",
                        message=f"Tensor {tensor_name!r}: dim {di} is non-positive; using -1 for Triton.",
                    )
                )
            di = -1
        out.append(di)
    return out


def _to_triton_dtype(dtype: str, *, issues: List[InspectionIssue], tensor_name: str) -> str:
    key = (dtype or "").strip().upper()
    mapped = _TRITON_DTYPE_MAP.get(key)
    if mapped:
        return mapped
    issues.append(
        InspectionIssue(
            level=IssueLevel.warning,
            code="TRITON_DTYPE_FALLBACK",
            source="TritonConfigBridge",
            message=f"Tensor {tensor_name!r}: unknown dtype {dtype!r}; falling back to TYPE_FP32 for Triton.",
        )
    )
    return "TYPE_FP32"


@dataclass
class TritonConfigBridge:
    model_name: str

    def generate(self, inspection: ModelInspectionResult) -> Tuple[str, List[InspectionIssue]]:
        issues: List[InspectionIssue] = list(inspection.issues or [])

        if inspection.format == ModelFormat.onnx:
            pbtxt = self._generate_onnx_config(inspection, issues=issues)
            return pbtxt, issues

        if inspection.format == ModelFormat.gguf:
            pbtxt = self._generate_gguf_python_config(issues=issues)
            return pbtxt, issues

        if inspection.format in {ModelFormat.safetensors, ModelFormat.pytorch}:
            pbtxt = self._generate_python_config_fallback(inspection, issues=issues)
            return pbtxt, issues

        issues.append(
            InspectionIssue(
                level=IssueLevel.error,
                code="TRITON_UNSUPPORTED_FORMAT",
                source="TritonConfigBridge",
                message=f"Unsupported format for Triton config generation: {inspection.format!r}.",
            )
        )
        return "", issues

    def _generate_onnx_config(self, inspection: ModelInspectionResult, *, issues: List[InspectionIssue]) -> str:
        inputs = list(inspection.io_info.inputs or [])
        outputs = list(inspection.io_info.outputs or [])
        if not inputs:
            inputs = [ModelIO(name="INPUT__0", dtype="FP32", shape=[-1])]
            issues.append(
                InspectionIssue(
                    level=IssueLevel.warning,
                    code="TRITON_IO_FALLBACK_INPUT",
                    source="TritonConfigBridge",
                    message="No inputs detected; generated fallback INPUT__0 (TYPE_FP32 dims [-1]).",
                )
            )
        if not outputs:
            outputs = [ModelIO(name="OUTPUT__0", dtype="FP32", shape=[-1])]
            issues.append(
                InspectionIssue(
                    level=IssueLevel.warning,
                    code="TRITON_IO_FALLBACK_OUTPUT",
                    source="TritonConfigBridge",
                    message="No outputs detected; generated fallback OUTPUT__0 (TYPE_FP32 dims [-1]).",
                )
            )

        lines = [
            f'name: "{self.model_name}"',
            'platform: "onnxruntime_onnx"',
            "max_batch_size: 0",
        ]
        for inp in inputs:
            lines.append("input {")
            lines.append(f'  name: "{inp.name}"')
            lines.append(f"  data_type: {_to_triton_dtype(inp.dtype, issues=issues, tensor_name=inp.name)}")
            for d in _dims_to_triton(list(inp.shape or []), issues=issues, tensor_name=inp.name):
                lines.append(f"  dims: {d}")
            lines.append("}")
        for out in outputs:
            lines.append("output {")
            lines.append(f'  name: "{out.name}"')
            lines.append(f"  data_type: {_to_triton_dtype(out.dtype, issues=issues, tensor_name=out.name)}")
            for d in _dims_to_triton(list(out.shape or []), issues=issues, tensor_name=out.name):
                lines.append(f"  dims: {d}")
            lines.append("}")
        return "\n".join(lines) + "\n"

    def _generate_gguf_python_config(self, *, issues: List[InspectionIssue]) -> str:
        # Static company pattern: GGUF served via python backend wrapper with prompt/text BYTES tensors.
        issues.append(
            InspectionIssue(
                level=IssueLevel.warning,
                code="TRITON_GGUF_PYTHON_SKELETON",
                source="TritonConfigBridge",
                message="GGUF does not map to a native Triton backend; generated Python backend skeleton IO (prompt/text as TYPE_BYTES).",
            )
        )
        return "\n".join(
            [
                f'name: "{self.model_name}"',
                'backend: "python"',
                "max_batch_size: 0",
                "input [",
                '  { name: "prompt" data_type: TYPE_BYTES dims: [ -1 ] }',
                "]",
                "output [",
                '  { name: "text" data_type: TYPE_BYTES dims: [ -1 ] }',
                "]",
                "",
            ]
        )

    def _generate_python_config_fallback(self, inspection: ModelInspectionResult, *, issues: List[InspectionIssue]) -> str:
        inputs = list(inspection.io_info.inputs or [])
        outputs = list(inspection.io_info.outputs or [])
        if not inputs:
            inputs = [ModelIO(name="INPUT__0", dtype="FP32", shape=[-1])]
            issues.append(
                InspectionIssue(
                    level=IssueLevel.warning,
                    code="TRITON_IO_FALLBACK_INPUT",
                    source="TritonConfigBridge",
                    message="No inputs detected; generated fallback INPUT__0 (TYPE_FP32 dims [-1]).",
                )
            )
        if not outputs:
            outputs = [ModelIO(name="OUTPUT__0", dtype="FP32", shape=[-1])]
            issues.append(
                InspectionIssue(
                    level=IssueLevel.warning,
                    code="TRITON_IO_FALLBACK_OUTPUT",
                    source="TritonConfigBridge",
                    message="No outputs detected; generated fallback OUTPUT__0 (TYPE_FP32 dims [-1]).",
                )
            )

        lines = [
            f'name: "{self.model_name}"',
            'backend: "python"',
            "max_batch_size: 0",
            "input [",
        ]
        for i, inp in enumerate(inputs):
            dtype = _to_triton_dtype(inp.dtype, issues=issues, tensor_name=inp.name)
            dims = _dims_to_triton(list(inp.shape or []), issues=issues, tensor_name=inp.name)
            comma = "," if i < len(inputs) - 1 else ""
            lines.append(
                f'  {{ name: "{inp.name}" data_type: {dtype} dims: [ ' + ", ".join(str(d) for d in dims) + f" ] }}{comma}"
            )
        lines.extend(
            [
                "]",
                "output [",
            ]
        )
        for i, out in enumerate(outputs):
            dtype = _to_triton_dtype(out.dtype, issues=issues, tensor_name=out.name)
            dims = _dims_to_triton(list(out.shape or []), issues=issues, tensor_name=out.name)
            comma = "," if i < len(outputs) - 1 else ""
            lines.append(
                f'  {{ name: "{out.name}" data_type: {dtype} dims: [ ' + ", ".join(str(d) for d in dims) + f" ] }}{comma}"
            )
        lines.append("]")
        lines.append("")
        return "\n".join(lines)

