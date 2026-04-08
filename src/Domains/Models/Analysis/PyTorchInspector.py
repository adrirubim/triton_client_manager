from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from src.Domains.Models.Schemas.ModelAnalysisReport import ModelIO
from src.Domains.Models.Schemas.ModelInspectionResult import InspectionIssue, IssueLevel


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
    issues: List[InspectionIssue]
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

    def _zip_preflight(self, path: Path) -> Tuple[int, int]:
        """
        Parse EOCD (End of Central Directory) from the tail of the file to obtain:
        - total entry count
        - central directory size

        This avoids `ZipFile.infolist()` materializing massive central directories in RAM.
        """
        # EOCD record is at least 22 bytes, plus up to 65535 bytes of comment.
        max_tail = 22 + 0xFFFF
        size = path.stat().st_size
        read_size = min(size, max_tail)
        with path.open("rb") as f:
            f.seek(size - read_size)
            tail = f.read(read_size)

        sig = b"PK\x05\x06"
        idx = tail.rfind(sig)
        if idx < 0:
            raise ValueError("EOCD signature not found")

        # EOCD structure (little-endian):
        # 0  4  signature
        # 4  2  disk number
        # 6  2  disk with CD start
        # 8  2  entries on this disk
        # 10 2  total entries
        # 12 4  central directory size
        # 16 4  central directory offset
        # 20 2  comment length
        eocd = tail[idx : idx + 22]
        if len(eocd) != 22:
            raise ValueError("EOCD truncated")

        total_entries = struct.unpack_from("<H", eocd, 10)[0]
        cd_size = struct.unpack_from("<I", eocd, 12)[0]
        return int(total_entries), int(cd_size)

    def run(self) -> PyTorchInspection:
        path = Path(self.model_path)
        if not path.is_file():
            raise FileNotFoundError(f"PyTorch file not found: {path}")

        warnings: List[str] = [
            "PyTorch .pt/.pth inspection is ZIP central-directory only; torch.load is intentionally not used (pickle/code execution risk).",
            "Input/output tensor shapes are unknown without executing or tracing the model.",
        ]
        issues: List[InspectionIssue] = []

        # Phase 2 requirement: static container inspection only.
        # We return unknown IO (empty lists) to avoid implying a contract.
        inputs: List[ModelIO] = []
        outputs: List[ModelIO] = []

        if not zipfile.is_zipfile(path):
            # Legacy/unknown container: we can only report that we did not parse it.
            warnings.append(
                "File is not a ZIP container (legacy or unsupported PyTorch serialization). No safe structure metadata extracted."
            )
            return PyTorchInspection(
                inputs=inputs,
                outputs=outputs,
                warnings=warnings,
                issues=issues,
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
            # Preflight EOCD to prevent RAM-based DoS via huge central directories.
            total_entries, cd_size = self._zip_preflight(path)
            member_count = int(total_entries)

            # Hard caps: protect CPU/RAM even before `ZipFile` materializes metadata.
            max_entries_hard = 200_000
            max_cd_size_bytes = 50 * 1024 * 1024  # 50 MB central directory

            if member_count > max_entries_hard or cd_size > max_cd_size_bytes:
                issues.append(
                    InspectionIssue(
                        level=IssueLevel.error,
                        code="PYTORCH_ZIP_TOO_LARGE",
                        source="PyTorchInspector",
                        message=(
                            "PyTorch ZIP rejected by preflight: "
                            f"entries={member_count} (cap={max_entries_hard}), "
                            f"central_dir_size={cd_size} bytes (cap={max_cd_size_bytes})."
                        ),
                    )
                )
                return PyTorchInspection(
                    inputs=inputs,
                    outputs=outputs,
                    warnings=warnings,
                    issues=issues,
                    container="zip_broken",
                    member_count=member_count,
                    members_recorded=0,
                    total_uncompressed_size_recorded=0,
                    total_compressed_size_recorded=0,
                    members=[],
                )

            with zipfile.ZipFile(path, "r") as zf:
                infos = (
                    zf.infolist()
                )  # central directory entries only (bounded by preflight)
                if member_count == 0:
                    member_count = int(len(infos))
                if int(member_count) > int(self.max_members):
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
            issues.append(
                InspectionIssue(
                    level=IssueLevel.error,
                    code="PYTORCH_ZIP_MALFORMED",
                    source="PyTorchInspector",
                    message=f"PyTorch ZIP inspection failed; treating container as broken. Error: {e}",
                )
            )
            return PyTorchInspection(
                inputs=inputs,
                outputs=outputs,
                warnings=warnings,
                issues=issues,
                container="zip_broken",
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
            issues=issues,
            container="zip",
            member_count=member_count,
            members_recorded=recorded,
            total_uncompressed_size_recorded=total_uncompressed,
            total_compressed_size_recorded=total_compressed,
            members=members,
        )
