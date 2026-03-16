from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Type

import yaml
from pydantic import BaseModel, ValidationError

from apps.manager.schemas.config_schema import (
    DockerConfig,
    JobsConfig,
    MinioConfig,
    TritonConfig,
    WebsocketConfig,
)


@dataclass
class ValidateConfigAction:
    """Valida los YAML de `apps/manager/config/` contra los esquemas Pydantic."""

    base_dir: str

    def _load_yaml(self, path: str) -> Dict:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"El fichero YAML `{path}` debe contener un objeto mapeable.")
        return data

    def _validate_one(self, filename: str, schema: Type[BaseModel]) -> None:
        path = os.path.join(self.base_dir, "config", filename)
        data = self._load_yaml(path)
        schema.model_validate(data)

    def run(self) -> None:
        """Lanza todas las validaciones. Lanza excepción si algo no es válido."""

        errors: Dict[str, str] = {}

        mapping: Dict[str, Type[BaseModel]] = {
            "jobs.yaml": JobsConfig,
            "websocket.yaml": WebsocketConfig,
            "docker.yaml": DockerConfig,
            "triton.yaml": TritonConfig,
            "minio.yaml": MinioConfig,
        }

        for filename, schema in mapping.items():
            try:
                self._validate_one(filename, schema)
            except (ValidationError, ValueError, FileNotFoundError) as exc:
                errors[filename] = str(exc)

        if errors:
            joined = "\n".join(f"- {name}: {msg}" for name, msg in errors.items())
            raise RuntimeError(f"Configuración inválida:\n{joined}")

