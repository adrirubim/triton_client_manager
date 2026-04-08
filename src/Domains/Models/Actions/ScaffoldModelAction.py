from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from src.Domains.Models.Schemas.TritonModelConfig import (
    TritonModelConfig,
    TritonModelIO,
)

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

_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _validate_model_name(name: str) -> str:
    if not isinstance(name, str) or not name or not _MODEL_NAME_RE.fullmatch(name):
        raise ValueError(
            "Invalid model name. Expected ^[a-zA-Z0-9._-]+$ (no slashes, no traversal)."
        )
    return name


def _ensure_within_root(path: Path, root: Path) -> Path:
    root_r = root.resolve()
    path_r = path.resolve()
    try:
        path_r.relative_to(root_r)
    except Exception as exc:
        raise ValueError(f"Refusing path outside sandbox root: {path_r}") from exc
    return path_r


@dataclass
class ScaffoldModelAction:
    """Generate a basic Triton model repository under `infra/models/`."""

    repo_root: str
    name: str
    fmt: ScaffoldModelFormat
    source_path: Optional[str] = None
    miniopath: Optional[str] = None
    overwrite: bool = False
    analyzer_version: str = "v2"

    def _target_root(self) -> Path:
        _validate_model_name(self.name)
        base = Path(self.repo_root) / "infra" / "models"
        target = base / self.name
        _ensure_within_root(target, base)
        return target

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

        # Support both legacy report shape (inputs/outputs) and Schema v2 payload
        # (inspection.io_info.inputs/outputs).
        if hasattr(report, "inspection") and getattr(
            report.inspection, "io_info", None
        ):
            raw_inputs = list(getattr(report.inspection.io_info, "inputs", []) or [])
            raw_outputs = list(getattr(report.inspection.io_info, "outputs", []) or [])
        else:
            raw_inputs = list(getattr(report, "inputs", []) or [])
            raw_outputs = list(getattr(report, "outputs", []) or [])

        inputs = [
            TritonModelIO(
                name=i.name,
                data_type=to_triton_dtype(i.dtype),
                dims=list(i.shape),
            )
            for i in raw_inputs
        ]
        outputs = [
            TritonModelIO(
                name=o.name,
                data_type=to_triton_dtype(o.dtype),
                dims=list(o.shape),
            )
            for o in raw_outputs
        ]

        # Minimal fallback when no IO is detected
        if not inputs:
            inputs = [TritonModelIO(name="INPUT__0", data_type="TYPE_FP32", dims=[-1])]
        if not outputs:
            outputs = [
                TritonModelIO(name="OUTPUT__0", data_type="TYPE_FP32", dims=[-1])
            ]

        default_model_filename = None
        if self.fmt == "onnx":
            # Our repo convention stores ONNX weights under 1/weights/model.onnx.
            # Triton defaults to 1/model.onnx unless we specify this.
            default_model_filename = "weights/model.onnx"

        return TritonModelConfig(
            name=self.name,
            platform=self._infer_platform(),
            default_model_filename=default_model_filename,
            max_batch_size=0,
            inputs=inputs,
            outputs=outputs,
        )

    def _render_config_pbtxt(self, cfg: TritonModelConfig) -> str:
        lines = [
            f'name: "{cfg.name}"',
            f'platform: "{cfg.platform}"',
        ]
        if cfg.default_model_filename:
            lines.append(f'default_model_filename: "{cfg.default_model_filename}"')
        lines.extend(
            [
                f"max_batch_size: {cfg.max_batch_size}",
            ]
        )
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
        _validate_model_name(self.name)
        root = self._target_root()
        existed_before = root.exists()

        try:
            if self.fmt not in ("onnx", "safetensors"):
                raise ValueError(f"Unsupported model format: {self.fmt!r}")

            if self.miniopath:
                fetched = FetchModelArtifactAction(
                    miniopath=self.miniopath, name=self.name
                ).run()
                src_weights = Path(fetched.local_path)
            elif self.source_path:
                src_weights = Path(self.source_path)
            else:
                raise ValueError(
                    "You must provide either `source_path` or `miniopath`."
                )

            if not src_weights.is_file():
                raise FileNotFoundError(f"Model weights file not found: {src_weights}")

            weights_dir = self._target_weights_dir()
            os.makedirs(weights_dir, exist_ok=True)

            # Copy weights
            ext = src_weights.suffix
            dst_weights = weights_dir / f"model{ext}"
            if dst_weights.exists() and not self.overwrite:
                raise FileExistsError(
                    f"Weights file already exists at {dst_weights} and overwrite=False. "
                    "Use overwrite=True to replace it explicitly."
                )
            shutil.copy2(src_weights, dst_weights)

            # Generate config.pbtxt
            # For onnx: real IO via analyzer. For safetensors: report tensors and use fallback IO.
            report = AnalyzeModelV2Action(
                miniopath=str(src_weights),
                name=self.name,
                category=ModelCategory.ml,
                format=self.fmt,
            ).run()
            cfg = self._build_config_from_report(report)
            config_text = self._render_config_pbtxt(cfg)
            cfg_path = root / "config.pbtxt"
            if (not cfg_path.exists()) or self.overwrite:
                tmp_cfg = cfg_path.with_name(cfg_path.name + ".tmp")
                tmp_cfg.write_text(config_text, encoding="utf-8")
                os.replace(str(tmp_cfg), str(cfg_path))

            # Create utils/timeit.py (placeholder) and model.py when using the Python backend
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

            # Write a simple manifest for identity/auditability (always safe to overwrite).
            manifest = {
                "timestamp": int(time.time()),
                "analyzer_version": self.analyzer_version,
                "model_format": self.fmt,
                "size_bytes": int(report.inspection.size_bytes),
            }
            manifest_path = root / "manifest.json"
            tmp_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
            tmp_manifest.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            os.replace(str(tmp_manifest), str(manifest_path))
        except Exception:
            # Rollback only if this scaffold created the model directory.
            if not existed_before and root.exists():
                shutil.rmtree(root, ignore_errors=True)
            raise
