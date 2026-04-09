from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

try:
    import onnx
    from onnx import TensorProto
except Exception:  # noqa: BLE001
    onnx = None  # type: ignore[assignment]
    TensorProto = None  # type: ignore[assignment]

from src.Domains.Models.Schemas.ModelAnalysisReport import ModelIO

_DTYPE_MAP = {
    TensorProto.FLOAT: "FP32",
    TensorProto.DOUBLE: "FP64",
    TensorProto.INT64: "INT64",
    TensorProto.INT32: "INT32",
    TensorProto.INT8: "INT8",
    TensorProto.UINT8: "UINT8",
    TensorProto.BOOL: "BOOL",
}


@dataclass(frozen=True)
class OnnxInspection:
    inputs: List[ModelIO]
    outputs: List[ModelIO]


@dataclass
class OnnxInspector:
    model_path: str

    def _tensor_to_io(self, tensor) -> ModelIO:
        elem_type = tensor.type.tensor_type.elem_type
        dtype = _DTYPE_MAP.get(elem_type, str(elem_type))
        dims: List[int] = []
        for dim in tensor.type.tensor_type.shape.dim:
            if dim.dim_value:
                dims.append(int(dim.dim_value))
            else:
                dims.append(-1)
        return ModelIO(name=tensor.name, dtype=dtype, shape=dims)

    def run(self) -> OnnxInspection:
        if onnx is None or TensorProto is None:
            raise ImportError(
                "ONNX inspection requires optional dependency 'onnx'. "
                "Install it via: pip install -r apps/manager/requirements-model-tools.txt"
            )

        path = Path(self.model_path)
        if not path.is_file():
            raise FileNotFoundError(f"ONNX model not found: {path}")

        model = onnx.load(str(path))
        graph = model.graph
        inputs = [self._tensor_to_io(v) for v in graph.input]
        outputs = [self._tensor_to_io(v) for v in graph.output]
        return OnnxInspection(inputs=inputs, outputs=outputs)
