from __future__ import annotations

import struct
import sys
import types
import zipfile
from pathlib import Path

import pytest

#
# Dependency stubs (must run BEFORE importing any project modules)
#
# Per your requirement: bypass missing ONNX dependency during import.
if "onnx" not in sys.modules:
    onnx_mod = types.ModuleType("onnx")

    class _TensorProto:
        FLOAT = 1
        DOUBLE = 11
        INT64 = 7
        INT32 = 6
        INT8 = 3
        UINT8 = 2
        BOOL = 9

    def _load(*_args, **_kwargs):
        raise RuntimeError("onnx is stubbed in static tests")

    onnx_mod.TensorProto = _TensorProto
    onnx_mod.load = _load
    sys.modules["onnx"] = onnx_mod

# Keep tests infra-free: these modules are imported at module-import time in the project.
sys.modules.setdefault("boto3", types.ModuleType("boto3"))
if "safetensors" not in sys.modules:
    st = types.ModuleType("safetensors")

    def _safe_open(*_args, **_kwargs):
        raise RuntimeError("safetensors is stubbed in static tests")

    st.safe_open = _safe_open
    sys.modules["safetensors"] = st

# Minimal pydantic stub via sys.modules mock (enough for ModelIO/ModelAnalysisReport construction).
if "pydantic" not in sys.modules:
    pyd = types.ModuleType("pydantic")

    class _FieldInfo:
        def __init__(self, default_factory=None):
            self.default_factory = default_factory

    def field(*, default_factory=None, **_kwargs):
        return _FieldInfo(default_factory=default_factory)

    class BaseModel:
        def __init__(self, **data):
            cls = self.__class__
            ann = getattr(cls, "__annotations__", {}) or {}
            for k in ann.keys():
                if k in data:
                    setattr(self, k, data[k])
                    continue
                default = getattr(cls, k, None)
                if isinstance(default, _FieldInfo) and callable(default.default_factory):
                    setattr(self, k, default.default_factory())
                elif isinstance(default, (list, dict, set)):
                    setattr(self, k, default.__class__(default))
                else:
                    setattr(self, k, default)
            for k, v in data.items():
                if not hasattr(self, k):
                    setattr(self, k, v)

    pyd.BaseModel = BaseModel
    pyd.Field = field
    sys.modules["pydantic"] = pyd


def _ensure_repo_root_on_path() -> None:
    """
    Tests run with cwd=apps/manager (see apps/manager/tests/conftest.py).
    Add repo root to sys.path so we can import `src.*`.
    """
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _write_gguf_string(b: bytearray, s: str) -> None:
    raw = s.encode("utf-8")
    b += struct.pack("<Q", len(raw))
    b += raw


def _make_minimal_gguf(*, with_chat_template: bool, kv_count: int = 1) -> bytes:
    """
    Minimal GGUF header + KV section, sufficient for Phase 1 KV-only parsing.
    Layout (little-endian):
      magic[4] "GGUF"
      version u32
      tensor_count u64
      kv_count u64
      kv entries:
        key: string (u64 len + bytes)
        value_type: u32
        value: depends on type (string uses u64 len + bytes)
    """
    out = bytearray()
    out += b"GGUF"
    out += struct.pack("<I", 2)  # version
    out += struct.pack("<Q", 0)  # tensor_count
    out += struct.pack("<Q", kv_count)  # kv_count

    if kv_count <= 0:
        return bytes(out)

    # key
    _write_gguf_string(out, "tokenizer.chat_template")
    # value_type STRING = 8 (as implemented in parser)
    out += struct.pack("<I", 8)
    if with_chat_template:
        _write_gguf_string(out, "Hello {{ messages }}")
    else:
        _write_gguf_string(out, "")

    return bytes(out)


def test_analyze_model_v2_detects_mock_gguf(tmp_path: Path) -> None:
    _ensure_repo_root_on_path()
    from src.Domains.Models.Actions.AnalyzeModelV2Action import AnalyzeModelV2Action
    from src.Domains.Models.Schemas.ModelAnalysisReport import (
        ModelCategory,
        ModelFormat,
    )

    p = tmp_path / "mock.gguf"
    gguf_bytes = _make_minimal_gguf(with_chat_template=True, kv_count=1)
    p.write_bytes(gguf_bytes)

    payload = AnalyzeModelV2Action(
        miniopath=str(p),
        name="mock",
        category=ModelCategory.llm,
        format=None,
    ).run()

    assert payload.inspection.format == ModelFormat.gguf
    assert payload.inspection.size_bytes == len(gguf_bytes)
    assert payload.inspection.io_info.inputs and payload.inspection.io_info.outputs
    assert any("GGUF inspection is KV-metadata only" in i.message for i in payload.inspection.issues)
    assert 'backend: "python"' in payload.triton_config_pbtxt
    assert 'name: "prompt"' in payload.triton_config_pbtxt
    assert 'name: "text"' in payload.triton_config_pbtxt


def test_mock_gguf_rejects_excessive_kv_count(tmp_path: Path) -> None:
    _ensure_repo_root_on_path()
    from src.Domains.Models.Actions.AnalyzeModelV2Action import AnalyzeModelV2Action
    from src.Domains.Models.Schemas.ModelAnalysisReport import ModelCategory

    # Cap is enforced inside parser; pick a kv_count that must fail immediately.
    p = tmp_path / "bad.gguf"
    payload = _make_minimal_gguf(with_chat_template=False, kv_count=50_001)
    p.write_bytes(payload)

    with pytest.raises(ValueError, match=r"kv_count too large"):
        AnalyzeModelV2Action(
            miniopath=str(p),
            name="bad",
            category=ModelCategory.llm,
            format=None,
        ).run()


def test_analyze_model_v2_inspects_mock_pytorch_zip_pt(tmp_path: Path) -> None:
    _ensure_repo_root_on_path()
    from src.Domains.Models.Actions.AnalyzeModelV2Action import AnalyzeModelV2Action
    from src.Domains.Models.Schemas.ModelAnalysisReport import (
        ModelCategory,
        ModelFormat,
    )

    p = tmp_path / "mock.pt"
    member_name = "data.pkl"
    member_bytes = b"abc123"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(member_name, member_bytes)

    payload = AnalyzeModelV2Action(
        miniopath=str(p),
        name="mock_pt",
        category=ModelCategory.llm,
        format=None,
    ).run()

    assert payload.inspection.format == ModelFormat.pytorch
    assert payload.inspection.io_info.inputs == []
    assert payload.inspection.io_info.outputs == []
    assert any("inspection is ZIP central-directory only" in i.message for i in payload.inspection.issues)
    assert any("inspection-only for safety" in i.message for i in payload.inspection.issues)
    assert any(f"~{len(member_bytes)} bytes" in i.message for i in payload.inspection.issues)


def test_analyze_model_v2_pytorch_non_zip_falls_back(tmp_path: Path) -> None:
    _ensure_repo_root_on_path()
    from src.Domains.Models.Actions.AnalyzeModelV2Action import AnalyzeModelV2Action
    from src.Domains.Models.Schemas.ModelAnalysisReport import (
        ModelCategory,
        ModelFormat,
    )

    p = tmp_path / "notzip.pth"
    p.write_bytes(b"not a zip")

    payload = AnalyzeModelV2Action(
        miniopath=str(p),
        name="notzip",
        category=ModelCategory.llm,
        format=None,
    ).run()

    assert payload.inspection.format == ModelFormat.pytorch
    assert payload.inspection.io_info.inputs == []
    assert payload.inspection.io_info.outputs == []
    assert any("not a ZIP container" in i.message for i in payload.inspection.issues)
    assert any("~0 bytes" in i.message for i in payload.inspection.issues)
