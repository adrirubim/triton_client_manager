# list_repo_files.py
import json
from dataclasses import asdict, dataclass, field
from pprint import pformat

from huggingface_hub import HfApi

UNSAFE = [".bin", ".pth", ".pt", "/"]
DF_G = 1024**3


@dataclass
class RepoInfo:
    hf_full: str = ""
    hf_user: str = ""
    hf_repo_name: str = ""
    hf_weight: float = 0.0
    revision: str = "main"

    hf_gguf: str = ""
    model_type: str = ""
    model_weight: float = 0.0

    include_files: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.hf_full.count("/") != 1:
            raise ValueError("Repo must be in the form 'user/model'")
        self.hf_user, self.hf_repo_name = self.hf_full.split("/")

    def to_g(self, bytes_size: int) -> float:
        return round(bytes_size / DF_G, 2)

    @classmethod
    def retrieve_info(cls, hf_full: str, hf_gguf: str = "", revision: str = "main") -> str:
        instance = cls(hf_full=hf_full, hf_gguf=hf_gguf, revision=revision)
        instance.execution()

        return json.dumps(asdict(instance))

    def execution(self):
        api = HfApi()
        info = api.model_info(repo_id=self.hf_full, revision=self.revision, files_metadata=True)

        siblings = info.siblings
        names = [(s.rfilename or "") for s in siblings]

        # Collect ggufs + safetensors
        ggufs = [n for n in names if n.lower().endswith(".gguf")]
        safes = [n for n in names if n.lower().endswith(".safetensors")]

        if ggufs and safes:
            raise ValueError("Repository can't contain gguf and safetensors")
        if not ggufs and not safes:
            raise ValueError("Repository doesn't contain weights")

        # Pick target weight file (if gguf repo)

        if not ggufs:
            self.model_type = "safetensors"

        else:
            self.model_type = "gguf"

            if self.hf_gguf:
                if not any(self.hf_gguf == n for n in ggufs):
                    raise ValueError(f"GGUF '{self.hf_gguf}' not found. Candidates: {pformat(ggufs)}")
            else:
                if len(ggufs) > 1:
                    raise ValueError(f"Multiple .gguf files found; please specify one: {pformat(ggufs)}")
                self.hf_gguf = ggufs[0]

        # Now iterate once, compute weights
        prohibited = [".bin", ".pth", ".pt", "/"]  # do NOT include "/"
        total_bytes = 0
        model_bytes = 0

        for s in siblings:
            name = s.rfilename or ""
            size = int(s.size or 0)

            if any(value in name.lower() for value in prohibited):
                continue

            # --- Weights Gguf ---
            if self.model_type == "gguf":
                if name.endswith(".gguf"):
                    if name == self.hf_gguf:
                        model_bytes += size
                    else:
                        continue

            # --- Weights Safe ---
            if self.model_type == "safetensors":
                if name.endswith(".safetensors"):
                    model_bytes += size

            # --- Whole Repo Weights ---
            total_bytes += size
            self.include_files.append(name)

        self.hf_weight = self.to_g(total_bytes)
        self.model_weight = self.to_g(model_bytes)
