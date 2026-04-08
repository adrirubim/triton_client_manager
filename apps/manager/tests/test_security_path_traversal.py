from __future__ import annotations

from pathlib import Path

import pytest
from src.Domains.Models.Actions.FetchModelArtifactAction import FetchModelArtifactAction
from src.Domains.Models.Actions.ScaffoldModelAction import ScaffoldModelAction


def test_fetch_model_artifact_rejects_traversal_name(tmp_path: Path) -> None:
    model_file = tmp_path / "m.onnx"
    model_file.write_bytes(b"dummy")

    with pytest.raises(ValueError):
        FetchModelArtifactAction(
            miniopath=str(model_file),
            name="../etc/passwd",
            cache_root=str(tmp_path / ".cache" / "models"),
        ).run()


def test_scaffold_rejects_traversal_name(tmp_path: Path) -> None:
    weights = tmp_path / "m.onnx"
    weights.write_bytes(b"dummy")

    with pytest.raises(ValueError):
        ScaffoldModelAction(
            repo_root=str(tmp_path),
            name="../../evil",
            fmt="onnx",  # type: ignore[arg-type]
            source_path=str(weights),
            overwrite=False,
        ).run()
