from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from src.Domains.Models.Actions.ScaffoldModelAction import ScaffoldModelAction


def test_scaffold_rolls_back_model_dir_on_failure(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path
    weights = tmp_path / "model.onnx"
    weights.write_bytes(b"fake-onnx")

    # Force a failure after the scaffold has created directories.
    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", boom)

    action = ScaffoldModelAction(
        repo_root=str(repo_root),
        name="ROLLBACK_TEST",
        fmt="onnx",
        source_path=str(weights),
        overwrite=False,
    )

    with pytest.raises(OSError):
        action.run()

    assert not (repo_root / "infra" / "models" / "ROLLBACK_TEST").exists()
