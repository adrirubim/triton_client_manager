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

_PBtxt_FORBIDDEN = {'"', "\n", "\r", "\t"}


def _sanitize_pbtxt_string(
    value: str,
    *,
    issues: List[InspectionIssue],
    field: str,
    replacement: str = "_",
) -> str:
    """
    Sanitize strings embedded in config.pbtxt.
    Triton pbtxt is sensitive to quotes/newlines; untrusted names must be made safe.
    """
    if not isinstance(value, str):
        issues.append(
            InspectionIssue(
                level=IssueLevel.warning,
                code="TRITON_PBTXT_SANITIZE",
                source="TritonConfigBridge",
                message=f"{field}: non-string value coerced to string for pbtxt.",
            )
        )
        value = str(value)

    if any(c in value for c in _PBtxt_FORBIDDEN):
        issues.append(
            InspectionIssue(
                level=IssueLevel.warning,
                code="TRITON_PBTXT_SANITIZE",
                source="TritonConfigBridge",
                message=f"{field}: sanitized forbidden characters for pbtxt safety.",
            )
        )
        out = []
        for c in value:
            out.append(replacement if c in _PBtxt_FORBIDDEN else c)
        value = "".join(out)

    # Avoid empty names after sanitization
    if not value:
        issues.append(
            InspectionIssue(
                level=IssueLevel.warning,
                code="TRITON_PBTXT_SANITIZE_EMPTY",
                source="TritonConfigBridge",
                message=f"{field}: empty value after sanitization; using fallback.",
            )
        )
        value = "UNNAMED"
    return value


def _dims_to_triton(
    dims: List[int], *, issues: List[InspectionIssue], tensor_name: str
) -> List[int]:
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


def _to_triton_dtype(
    dtype: str, *, issues: List[InspectionIssue], tensor_name: str
) -> str:
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


def _should_enable_batching(
    inputs: List[ModelIO],
    outputs: List[ModelIO],
    *,
    issues: List[InspectionIssue],
) -> bool:
    """
    Conservative batching heuristic:
    - Enable batching only when every tensor has rank >= 1 and the first dim is either -1 or 1.
    - Disable otherwise and emit a warning so callers understand why batching is off.
    """

    tensors = list(inputs or []) + list(outputs or [])
    if not tensors:
        issues.append(
            InspectionIssue(
                level=IssueLevel.warning,
                code="TRITON_BATCHING_DISABLED",
                source="TritonConfigBridge",
                message="Batching disabled: no IO tensors available to infer a safe batch dimension.",
            )
        )
        return False

    for t in tensors:
        shape = list(t.shape or [])
        if len(shape) < 1:
            issues.append(
                InspectionIssue(
                    level=IssueLevel.warning,
                    code="TRITON_BATCHING_DISABLED",
                    source="TritonConfigBridge",
                    message=f"Batching disabled: tensor {t.name!r} has rank {len(shape)} (needs >= 1).",
                )
            )
            return False
        try:
            d0 = int(shape[0])
        except Exception:
            issues.append(
                InspectionIssue(
                    level=IssueLevel.warning,
                    code="TRITON_BATCHING_DISABLED",
                    source="TritonConfigBridge",
                    message=f"Batching disabled: tensor {t.name!r} has non-integer first dim {shape[0]!r}.",
                )
            )
            return False

        if d0 not in (-1, 1):
            issues.append(
                InspectionIssue(
                    level=IssueLevel.warning,
                    code="TRITON_BATCHING_DISABLED",
                    source="TritonConfigBridge",
                    message=(
                        f"Batching disabled: tensor {t.name!r} has first dim {d0}, "
                        "which is not recognized as a safe batch dimension (-1 or 1)."
                    ),
                )
            )
            return False

    return True


def _pbtxt_dims_for_tensor(
    shape: List[int],
    *,
    tensor_name: str,
    issues: List[InspectionIssue],
    batching_enabled: bool,
) -> List[int]:
    dims = list(shape or [])
    if batching_enabled and len(dims) >= 1:
        # With max_batch_size > 0, Triton expects dims excluding the batch dimension.
        dims = dims[1:]
    return _dims_to_triton(dims, issues=issues, tensor_name=tensor_name)


@dataclass
class TritonConfigBridge:
    model_name: str

    def _instance_group_block(
        self, inspection: ModelInspectionResult, *, issues: List[InspectionIssue]
    ) -> List[str]:
        """
        Optional GPU-aware config:

        If `inspection.metadata["gpu_id"]` is provided, emit an `instance_group`
        stanza pinning the model to that GPU id.

        This is best-effort and backwards compatible: when gpu_id is absent or
        invalid, no instance_group is emitted.
        """
        meta = getattr(inspection, "metadata", {}) or {}
        gpu_id = meta.get("gpu_id") if isinstance(meta, dict) else None
        if gpu_id is None:
            return []
        try:
            gid = int(gpu_id)
        except Exception:
            issues.append(
                InspectionIssue(
                    level=IssueLevel.warning,
                    code="TRITON_GPU_ID_INVALID",
                    source="TritonConfigBridge",
                    message=f"metadata.gpu_id is not an integer ({gpu_id!r}); ignoring instance_group.",
                )
            )
            return []
        if gid < 0:
            issues.append(
                InspectionIssue(
                    level=IssueLevel.warning,
                    code="TRITON_GPU_ID_INVALID",
                    source="TritonConfigBridge",
                    message=f"metadata.gpu_id is negative ({gid}); ignoring instance_group.",
                )
            )
            return []
        return [
            "instance_group {",
            "  kind: KIND_GPU",
            f"  gpus: {gid}",
            "}",
        ]

    def generate(
        self, inspection: ModelInspectionResult
    ) -> Tuple[str, List[InspectionIssue]]:
        issues: List[InspectionIssue] = list(inspection.issues or [])
        safe_model_name = _sanitize_pbtxt_string(
            self.model_name, issues=issues, field="model_name"
        )
        self.model_name = safe_model_name

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

    def _generate_onnx_config(
        self, inspection: ModelInspectionResult, *, issues: List[InspectionIssue]
    ) -> str:
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

        batching_enabled = _should_enable_batching(inputs, outputs, issues=issues)
        max_batch_size = 8 if batching_enabled else 0

        lines = [
            f'name: "{self.model_name}"',
            'platform: "onnxruntime_onnx"',
            f"max_batch_size: {max_batch_size}",
        ]
        lines.extend(self._instance_group_block(inspection, issues=issues))
        for inp in inputs:
            safe_in_name = _sanitize_pbtxt_string(
                inp.name, issues=issues, field="input.name"
            )
            lines.append("input {")
            lines.append(f'  name: "{safe_in_name}"')
            lines.append(
                f"  data_type: {_to_triton_dtype(inp.dtype, issues=issues, tensor_name=safe_in_name)}"
            )
            for d in _pbtxt_dims_for_tensor(
                list(inp.shape or []),
                tensor_name=safe_in_name,
                issues=issues,
                batching_enabled=batching_enabled,
            ):
                lines.append(f"  dims: {d}")
            lines.append("}")
        for out in outputs:
            safe_out_name = _sanitize_pbtxt_string(
                out.name, issues=issues, field="output.name"
            )
            lines.append("output {")
            lines.append(f'  name: "{safe_out_name}"')
            lines.append(
                f"  data_type: {_to_triton_dtype(out.dtype, issues=issues, tensor_name=safe_out_name)}"
            )
            for d in _pbtxt_dims_for_tensor(
                list(out.shape or []),
                tensor_name=safe_out_name,
                issues=issues,
                batching_enabled=batching_enabled,
            ):
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

    def _generate_python_config_fallback(
        self, inspection: ModelInspectionResult, *, issues: List[InspectionIssue]
    ) -> str:
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

        batching_enabled = _should_enable_batching(inputs, outputs, issues=issues)
        max_batch_size = 8 if batching_enabled else 0

        lines = [
            f'name: "{self.model_name}"',
            'backend: "python"',
            f"max_batch_size: {max_batch_size}",
        ]
        lines.extend(self._instance_group_block(inspection, issues=issues))
        lines.extend(
            [
            "input [",
            ]
        )
        for i, inp in enumerate(inputs):
            safe_in_name = _sanitize_pbtxt_string(
                inp.name, issues=issues, field="input.name"
            )
            dtype = _to_triton_dtype(inp.dtype, issues=issues, tensor_name=inp.name)
            dims = _pbtxt_dims_for_tensor(
                list(inp.shape or []),
                tensor_name=safe_in_name,
                issues=issues,
                batching_enabled=batching_enabled,
            )
            comma = "," if i < len(inputs) - 1 else ""
            lines.append(
                f'  {{ name: "{safe_in_name}" data_type: {dtype} dims: [ '
                + ", ".join(str(d) for d in dims)
                + f" ] }}{comma}"
            )
        lines.extend(
            [
                "]",
                "output [",
            ]
        )
        for i, out in enumerate(outputs):
            safe_out_name = _sanitize_pbtxt_string(
                out.name, issues=issues, field="output.name"
            )
            dtype = _to_triton_dtype(out.dtype, issues=issues, tensor_name=out.name)
            dims = _pbtxt_dims_for_tensor(
                list(out.shape or []),
                tensor_name=safe_out_name,
                issues=issues,
                batching_enabled=batching_enabled,
            )
            comma = "," if i < len(outputs) - 1 else ""
            lines.append(
                f'  {{ name: "{safe_out_name}" data_type: {dtype} dims: [ '
                + ", ".join(str(d) for d in dims)
                + f" ] }}{comma}"
            )
        lines.append("]")
        lines.append("")
        return "\n".join(lines)
