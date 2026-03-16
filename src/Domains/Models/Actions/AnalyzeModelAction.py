from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import onnx
from onnx import TensorProto
from pydantic import BaseModel, Field


class AnalyzedIO(BaseModel):
    name: str
    dtype: str
    shape: List[int] = Field(default_factory=list)


class AnalyzeModelReport(BaseModel):
    path: str
    name: str
    inputs: List[AnalyzedIO] = Field(default_factory=list)
    outputs: List[AnalyzedIO] = Field(default_factory=list)


_DTYPE_MAP = {
    TensorProto.FLOAT: "FP32",
    TensorProto.DOUBLE: "FP64",
    TensorProto.INT64: "INT64",
    TensorProto.INT32: "INT32",
    TensorProto.INT8: "INT8",
    TensorProto.UINT8: "UINT8",
    TensorProto.BOOL: "BOOL",
}


@dataclass
class AnalyzeModelAction:
    """
    Inspecciona un fichero ONNX y devuelve un informe tipado de sus entradas/salidas.
    """

    model_path: str
    name: str

    def _load_model(self) -> onnx.ModelProto:
        path = Path(self.model_path)
        if not path.is_file():
            raise FileNotFoundError(f"Modelo ONNX no encontrado en {path}")
        return onnx.load(str(path))

    def _tensor_to_io(self, tensor) -> AnalyzedIO:
        dtype = _DTYPE_MAP.get(tensor.type.tensor_type.elem_type, str(tensor.type.tensor_type.elem_type))
        dims: List[int] = []
        for dim in tensor.type.tensor_type.shape.dim:
            if dim.dim_value:
                dims.append(int(dim.dim_value))
            else:
                # Dimensión dinámica o simbólica: la representamos como -1.
                dims.append(-1)
        return AnalyzedIO(
            name=tensor.name,
            dtype=dtype,
            shape=dims,
        )

    def build_report(self) -> AnalyzeModelReport:
        model = self._load_model()
        graph = model.graph

        inputs = [self._tensor_to_io(v) for v in graph.input]
        outputs = [self._tensor_to_io(v) for v in graph.output]

        return AnalyzeModelReport(
            path=self.model_path,
            name=self.name,
            inputs=inputs,
            outputs=outputs,
        )

    def run(self, *, print_json: bool = True) -> AnalyzeModelReport:
        report = self.build_report()
        if print_json:
            print(report.model_dump_json(indent=2))
        return report

