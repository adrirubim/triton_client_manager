from __future__ import annotations

from src.Domains.Models.Analysis.TritonConfigBridge import TritonConfigBridge
from src.Domains.Models.Schemas.ModelAnalysisReport import ModelFormat, ModelIO
from src.Domains.Models.Schemas.ModelInspectionResult import (
    ModelInspectionResult,
    ModelIOInfo,
)


def _inspect(
    fmt: ModelFormat,
    *,
    inputs: list[ModelIO] | None = None,
    outputs: list[ModelIO] | None = None,
):
    return ModelInspectionResult(
        format=fmt,
        size_bytes=123,
        io_info=ModelIOInfo(inputs=inputs or [], outputs=outputs or []),
        issues=[],
    )


def test_sanitize_pbtxt_string_replaces_quotes_and_newlines_via_generate() -> None:
    bridge = TritonConfigBridge(model_name='evil"\nname')
    pbtxt, issues = bridge.generate(
        _inspect(
            ModelFormat.onnx,
            inputs=[ModelIO(name='in"\n\t', dtype="FP32", shape=[-1, 3])],
            outputs=[ModelIO(name="out", dtype="FP32", shape=[-1, 3])],
        )
    )

    # pbtxt uses quotes for string fields, but untrusted content must be sanitized
    # so that raw quotes/newlines from user values do not survive inside the value.
    assert 'evil"\nname' not in pbtxt
    assert 'in"\n\t' not in pbtxt
    assert issues  # should record warnings for sanitization


def test_batching_enabled_only_for_safe_first_dim_minus1_or_1() -> None:
    # Safe: first dim -1 => batching enabled => max_batch_size 8
    bridge = TritonConfigBridge(model_name="m")
    pbtxt, _issues = bridge.generate(
        _inspect(
            ModelFormat.onnx,
            inputs=[ModelIO(name="in", dtype="FP32", shape=[-1, 3])],
            outputs=[ModelIO(name="out", dtype="FP32", shape=[-1, 2])],
        )
    )
    assert "max_batch_size: 8" in pbtxt

    # Unsafe: first dim 2 => batching disabled => max_batch_size 0
    bridge2 = TritonConfigBridge(model_name="m2")
    pbtxt2, issues2 = bridge2.generate(
        _inspect(
            ModelFormat.onnx,
            inputs=[ModelIO(name="in", dtype="FP32", shape=[2, 3])],
            outputs=[ModelIO(name="out", dtype="FP32", shape=[2, 2])],
        )
    )
    assert "max_batch_size: 0" in pbtxt2
    assert any("Batching disabled" in i.message for i in issues2)


def test_dimension_coercion_nonpositive_dims_become_minus1() -> None:
    bridge = TritonConfigBridge(model_name="m")
    pbtxt, issues = bridge.generate(
        _inspect(
            ModelFormat.onnx,
            inputs=[ModelIO(name="in", dtype="FP32", shape=[-1, 0, -5])],
            outputs=[ModelIO(name="out", dtype="FP32", shape=[-1, 1])],
        )
    )

    # With batching enabled (first dim -1), pbtxt dims exclude batch dim and non-positive become -1.
    assert "max_batch_size: 8" in pbtxt
    assert "dims: -1" in pbtxt
    assert any(i.code in {"TRITON_DIM_NONPOSITIVE", "TRITON_DIM_COERCE"} for i in issues)
