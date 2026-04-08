from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from safetensors import safe_open

from src.Domains.Models.Schemas.ModelAnalysisReport import ModelIO


_DTYPE_MAP = {
    "F16": "FP16",
    "F32": "FP32",
    "F64": "FP64",
    "I8": "INT8",
    "I16": "INT16",
    "I32": "INT32",
    "I64": "INT64",
    "U8": "UINT8",
    "U16": "UINT16",
    "U32": "UINT32",
    "U64": "UINT64",
    "BOOL": "BOOL",
}


@dataclass(frozen=True)
class SafetensorsInspection:
    tensors: List[ModelIO]


@dataclass
class SafetensorsInspector:
    model_path: str

    def run(self) -> SafetensorsInspection:
        path = Path(self.model_path)
        if not path.is_file():
            raise FileNotFoundError(f"safetensors file not found: {path}")

        ios: List[ModelIO] = []
        with safe_open(str(path), framework="np") as f:
            for name in f.keys():
                tensor = f.get_tensor(name)
                dtype = _DTYPE_MAP.get(str(tensor.dtype).upper(), str(tensor.dtype))
                shape = list(tensor.shape)
                ios.append(ModelIO(name=name, dtype=dtype, shape=shape))

        return SafetensorsInspection(tensors=ios)
