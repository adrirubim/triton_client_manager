"""
Modo desarrollo para Triton Client Manager.

Arranca únicamente los hilos necesarios para desarrollo local:
- JobThread (colas, backpressure, métricas).
- WebSocketThread (endpoint /ws y /metrics vía FastAPI).

No inicializa OpenStack, Docker ni Triton reales para evitar dependencias
externas. En su lugar inyecta "backends" de prueba ligeros que permiten:
- Probar autenticación WebSocket.
- Consultar `info.queue_stats`.
- Generar métricas para Prometheus/Grafana de forma estable.

Uso:
    cd MANAGER
    .venv/bin/python dev_server.py
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from yaml import safe_load

from classes.job import JobThread
from classes.websocket import WebSocketThread
from utils.logging_config import configure_logging

logger = logging.getLogger(__name__)


@dataclass
class DevBackend:
    """
    Backend "dummy" para modo desarrollo.

    Proporciona solo los atributos mínimos esperados por los handlers de jobs.
    Si en algún momento se invocan métodos no soportados, se lanza un error
    claro para que el desarrollador sepa que está usando una ruta aún no
    implementada en modo dev.
    """

    name: str

    def __getattr__(self, item: str):
        raise NotImplementedError(
            f"'{self.name}' no implementa '{item}' en modo dev. "
            "Usa servicios reales o extiende DevBackend para este caso."
        )


def _load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return safe_load(f)


def main() -> None:
    # Aseguramos que el cwd es MANAGER para rutas relativas de config
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)

    # Logging estructurado coherente con el resto del proyecto
    configure_logging()
    logger.info(
        "Starting Triton Client Manager in DEV mode",
        extra={"client_uuid": "-", "job_id": "-", "job_type": "dev_startup"},
    )

    # Carga de configuración mínima necesaria para dev
    config_job = _load_yaml(os.path.join("config", "jobs.yaml"))
    config_ws = _load_yaml(os.path.join("config", "websocket.yaml"))

    # Backends de prueba (sin OpenStack/Docker/Triton reales)
    docker_backend = DevBackend(name="DockerDevBackend")
    openstack_backend = DevBackend(name="OpenstackDevBackend")
    triton_backend = DevBackend(name="TritonDevBackend")

    # Wiring de JobThread y WebSocketThread
    job = JobThread(**config_job)
    job.docker = docker_backend
    job.openstack = openstack_backend
    job.triton = triton_backend

    websocket = WebSocketThread(
        **config_ws,
        on_message=job.on_message,
        get_queue_stats=job.get_queue_stats,
    )
    job.websocket = websocket.send_to_client

    # Arranque de hilos
    job.start()
    websocket.start()

    if not job.wait_until_ready(timeout=10):
        raise RuntimeError("JobThread failed to initialize in dev mode")
    if not websocket.wait_until_ready(timeout=10):
        raise RuntimeError("WebSocketThread failed to initialize in dev mode")

    logger.info(
        "DEV server ready: WebSocket and metrics exposed on %s:%s",
        config_ws.get("host", "0.0.0.0"),
        config_ws.get("port"),
        extra={"client_uuid": "-", "job_id": "-", "job_type": "dev_startup"},
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info(
            "Shutting down DEV server...",
            extra={"client_uuid": "-", "job_id": "-", "job_type": "dev_shutdown"},
        )
        job.stop()
        websocket.stop()
        websocket.join(timeout=5)
        logger.info(
            "DEV server stopped cleanly",
            extra={"client_uuid": "-", "job_id": "-", "job_type": "dev_shutdown"},
        )


if __name__ == "__main__":
    main()
