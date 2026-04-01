from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from src.Domains.Models.Schemas.ModelAnalysisReport import ModelIO


@dataclass(frozen=True)
class PyTorchZipMember:
    name: str
    compressed_size: int
    uncompressed_size: int


@dataclass(frozen=True)
class PyTorchInspection:
    inputs: List[ModelIO]
    outputs: List[ModelIO]
    warnings: List[str]
    container: str
    member_count: int
    members_recorded: int
    total_uncompressed_size_recorded: int
    total_compressed_size_recorded: int
    members: List[PyTorchZipMember]


@dataclass
class PyTorchInspector:
    model_path: str
    max_members: int = 2000

    def run(self) -> PyTorchInspection:
        path = Path(self.model_path)
        if not path.is_file():
            raise FileNotFoundError(f"PyTorch file not found: {path}")

        warnings: List[str] = [
            "PyTorch .pt/.pth inspection is ZIP central-directory only; torch.load is intentionally not used (pickle/code execution risk).",
            "Input/output tensor shapes are unknown without executing or tracing the model.",
        ]

        # Phase 2 requirement: static container inspection only.
        # We return unknown IO (empty lists) to avoid implying a contract.
        inputs: List[ModelIO] = []
        outputs: List[ModelIO] = []

        if not zipfile.is_zipfile(path):
            # Legacy/unknown container: we can only report that we did not parse it.
            warnings.append("File is not a ZIP container (legacy or unsupported PyTorch serialization). No safe structure metadata extracted.")
            return PyTorchInspection(
                inputs=inputs,
                outputs=outputs,
                warnings=warnings,
                container="unknown",
                member_count=0,
                members_recorded=0,
                total_uncompressed_size_recorded=0,
                total_compressed_size_recorded=0,
                members=[],
            )

        members: List[PyTorchZipMember] = []
        member_count = 0
        recorded = 0
        total_uncompressed = 0
        total_compressed = 0

        try:
            with zipfile.ZipFile(path, "r") as zf:
                infos = zf.infolist()  # central directory entries only
                member_count = int(len(infos))
                if member_count > int(self.max_members):
                    warnings.append(
                        f"PyTorch ZIP has many members ({member_count}); recorded list is truncated to max_members={int(self.max_members)}."
                    )
                for i in infos[: int(self.max_members)]:
                    recorded += 1
                    cs = int(i.compress_size)
                    us = int(i.file_size)
                    total_compressed += cs
                    total_uncompressed += us
                    members.append(
                        PyTorchZipMember(
                            name=str(i.filename),
                            compressed_size=cs,
                            uncompressed_size=us,
                        )
                    )
        except Exception as e:
            # Stay infra-free and resilient: do not crash the whole analysis pipeline.
            warnings.append(f"PyTorch ZIP inspection failed; falling back to file-only info. Error: {e}")
            return PyTorchInspection(
                inputs=inputs,
                outputs=outputs,
                warnings=warnings,
                container="zip",
                member_count=member_count,
                members_recorded=recorded,
                total_uncompressed_size_recorded=total_uncompressed,
                total_compressed_size_recorded=total_compressed,
                members=members,
            )

        return PyTorchInspection(
            inputs=inputs,
            outputs=outputs,
            warnings=warnings,
            container="zip",
            member_count=member_count,
            members_recorded=recorded,
            total_uncompressed_size_recorded=total_uncompressed,
            total_compressed_size_recorded=total_compressed,
            members=members,
        )

