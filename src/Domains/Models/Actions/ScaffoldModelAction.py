from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from apps.manager.schemas.triton_model_config import TritonModelConfig, TritonModelIO

from src.Domains.Models.Actions.AnalyzeModelV2Action import AnalyzeModelV2Action
from src.Domains.Models.Actions.FetchModelArtifactAction import FetchModelArtifactAction
from src.Domains.Models.Schemas.ModelAnalysisReport import ModelCategory


ScaffoldModelFormat = Literal["onnx", "safetensors"]

_TRITON_DTYPE_MAP = {
    "FP16": "TYPE_FP16",
    "FP32": "TYPE_FP32",
    "FP64": "TYPE_FP64",
    "INT8": "TYPE_INT8",
    "INT16": "TYPE_INT16",
    "INT32": "TYPE_INT32",
    "INT64": "TYPE_INT64",
    "UINT8": "TYPE_UINT8",
    "BOOL": "TYPE_BOOL",
    "BYTES": "TYPE_BYTES",
    "STRING": "TYPE_STRING",
}


@dataclass
class ScaffoldModelAction:
    """Generate a basic Triton model repository under `infra/models/`."""

    repo_root: str
    name: str
    fmt: ScaffoldModelFormat
    source_path: Optional[str] = None
    miniopath: Optional[str] = None
    overwrite: bool = False

    def _target_root(self) -> Path:
        return Path(self.repo_root) / "infra" / "models" / self.name

    def _target_weights_dir(self) -> Path:
        return self._target_root() / "1" / "weights"

    def _infer_platform(self) -> str:
        if self.fmt == "onnx":
            return "onnxruntime_onnx"
        if self.fmt == "safetensors":
            # Triton has no native backend for safetensors: scaffold as Python backend wrapper.
            return "python"
        # Extra safety: should not be reachable thanks to ModelFormat.
        raise ValueError(f"Unsupported model format: {self.fmt!r}")

    def _build_config_from_report(self, report) -> TritonModelConfig:
        def to_triton_dtype(dtype: str) -> str:
            return _TRITON_DTYPE_MAP.get(dtype.upper(), "TYPE_FP32")

        inputs = [
            TritonModelIO(name=i.name, data_type=to_triton_dtype(i.dtype), dims=list(i.shape))
            for i in (report.inputs or [])
        ]
        outputs = [
            TritonModelIO(name=o.name, data_type=to_triton_dtype(o.dtype), dims=list(o.shape))
            for o in (report.outputs or [])
        ]

        # Fallback mínimo si no hay IO detectado
        if not inputs:
            inputs = [TritonModelIO(name="INPUT__0", data_type="TYPE_FP32", dims=[-1])]
        if not outputs:
            outputs = [TritonModelIO(name="OUTPUT__0", data_type="TYPE_FP32", dims=[-1])]

        return TritonModelConfig(
            name=self.name,
            platform=self._infer_platform(),
            max_batch_size=0,
            inputs=inputs,
            outputs=outputs,
        )

    def _render_config_pbtxt(self, cfg: TritonModelConfig) -> str:
        lines = [
            f'name: "{cfg.name}"',
            f'platform: "{cfg.platform}"',
            f"max_batch_size: {cfg.max_batch_size}",
        ]
        for inp in cfg.inputs:
            lines.append("input {")
            lines.append(f'  name: "{inp.name}"')
            lines.append(f"  data_type: {inp.data_type}")
            for d in inp.dims:
                lines.append(f"  dims: {d}")
            lines.append("}")
        for out in cfg.outputs:
            lines.append("output {")
            lines.append(f'  name: "{out.name}"')
            lines.append(f"  data_type: {out.data_type}")
            for d in out.dims:
                lines.append(f"  dims: {d}")
            lines.append("}")
        return "\n".join(lines) + "\n"

    def run(self) -> None:
        if self.fmt not in ("onnx", "safetensors"):
            raise ValueError(f"Unsupported model format: {self.fmt!r}")

        if self.miniopath:
            fetched = FetchModelArtifactAction(miniopath=self.miniopath, name=self.name).run()
            src_weights = Path(fetched.local_path)
        elif self.source_path:
            src_weights = Path(self.source_path)
        else:
            raise ValueError("You must provide either `source_path` or `miniopath`.")

        if not src_weights.is_file():
            raise FileNotFoundError(f"Model weights file not found: {src_weights}")

        root = self._target_root()
        weights_dir = self._target_weights_dir()
        os.makedirs(weights_dir, exist_ok=True)

        # Copia de pesos
        ext = src_weights.suffix
        dst_weights = weights_dir / f"model{ext}"
        if dst_weights.exists() and not self.overwrite:
            raise FileExistsError(
                f"Weights file already exists at {dst_weights} and overwrite=False. "
                "Use overwrite=True to replace it explicitly."
            )
        shutil.copy2(src_weights, dst_weights)

        # Generar config.pbtxt
        # Para onnx: IO real via analyzer. Para safetensors: reporta tensores y usa fallback IO.
        report = AnalyzeModelV2Action(
            miniopath=str(src_weights),
            name=self.name,
            category=ModelCategory.ml,
            format=self.fmt,
        ).run()
        cfg = self._build_config_from_report(report)
        config_text = self._render_config_pbtxt(cfg)
        with open(root / "config.pbtxt", "w", encoding="utf-8") as f:
            f.write(config_text)

        # Crear utils/timeit.py (placeholder) y model.py cuando usemos python backend
        utils_dir = root / "1" / "utils"
        utils_dir.mkdir(parents=True, exist_ok=True)
        timeit_path = utils_dir / "timeit.py"
        if not timeit_path.exists() or self.overwrite:
            timeit_path.write_text(
                "import time\n\n\ndef time_it(fn):\n    def wrapper(*args, **kwargs):\n        start = time.perf_counter()\n        out = fn(*args, **kwargs)\n        return out, time.perf_counter() - start\n\n    return wrapper\n",
                encoding="utf-8",
            )

        if self.fmt == "safetensors":
            model_py = root / "1" / "model.py"
            if not model_py.exists() or self.overwrite:
                model_py.write_text(
                    "import triton_python_backend_utils as pb_utils\n\n\nclass TritonPythonModel:\n    def initialize(self, args):\n        raise pb_utils.TritonModelException('safetensors scaffold created: implement inference wrapper in model.py')\n\n    def execute(self, requests):\n        return [pb_utils.InferenceResponse(error=pb_utils.TritonError('not implemented')) for _ in requests]\n",
                    encoding="utf-8",
                )

