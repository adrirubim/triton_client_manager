from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.Domains.Models.Schemas.ModelAnalysisReport import ModelIO

from src.Domains.Models.Analysis.GgufKVParser import (
    GgufKVParseError,
    GgufKVParseResult,
    parse_gguf_kv,
)


@dataclass(frozen=True)
class GgufInspection:
    kv: Dict[str, Any]
    chat_template: Optional[str]
    inputs: List[ModelIO]
    outputs: List[ModelIO]
    warnings: List[str]
    gguf_version: int
    tensor_count: int
    kv_count: int


@dataclass
class GgufInspector:
    model_path: str

    def run(self) -> GgufInspection:
        path = Path(self.model_path)
        if not path.is_file():
            raise FileNotFoundError(f"GGUF model not found: {path}")

        try:
            parsed: GgufKVParseResult = parse_gguf_kv(str(path))
        except GgufKVParseError as e:
            # Keep the interface similar to other inspectors: raise for invalid file.
            raise ValueError(f"GGUF KV parsing failed: {e}") from e

        kv = parsed.kv

        warnings: List[str] = []
        tmpl = kv.get("tokenizer.chat_template")
        chat_template = tmpl if isinstance(tmpl, str) and tmpl.strip() else None
        if chat_template is None:
            warnings.append(
                "GGUF KV metadata has no tokenizer.chat_template (chat template unknown)."
            )

        # Phase 1 requirement: static KV-only parsing. We do not load weights and we do not
        # attempt to infer real IO tensors. Provide unknown placeholders when needed.
        inputs: List[ModelIO] = []
        outputs: List[ModelIO] = []

        # Minimal hint: if chat_template exists, we can model a text-in/text-out contract as unknown.
        if chat_template:
            inputs = [ModelIO(name="prompt", dtype="BYTES", shape=[-1])]
            outputs = [ModelIO(name="text", dtype="BYTES", shape=[-1])]
            warnings.append(
                "GGUF IO is inferred as a minimal prompt/text contract placeholder; GGUF does not expose a Triton IO schema in KV."
            )
        else:
            warnings.append(
                "GGUF IO is unknown; no safe static IO contract can be inferred from KV metadata alone."
            )

        return GgufInspection(
            kv=kv,
            chat_template=chat_template,
            inputs=inputs,
            outputs=outputs,
            warnings=warnings,
            gguf_version=parsed.version,
            tensor_count=parsed.tensor_count,
            kv_count=parsed.kv_count,
        )
