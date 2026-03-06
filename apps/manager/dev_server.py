"""
Development mode entrypoint for Triton Client Manager.

Starts only the threads needed for local development:
- JobThread (queues, backpressure, metrics).
- WebSocketThread (`/ws` and `/metrics` via FastAPI).

It does **not** initialise real OpenStack, Docker or Triton backends to avoid
external dependencies. Instead it injects lightweight dummy backends that let
you:
- Test WebSocket authentication.
- Query `info.queue_stats`.
- Generate stable metrics for Prometheus / Grafana.

Usage:
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
    Minimal dummy backend for development mode.

    Provides only the minimum attributes expected by job handlers. If a method
    that is not supported in dev mode is called, a clear error is raised so
    the developer knows they are hitting a code path that is not yet supported
    in this mode.
    """

    name: str

    def __getattr__(self, item: str):
        raise NotImplementedError(
            f"'{self.name}' does not implement '{item}' in dev mode. "
            "Use real services or extend DevBackend for this use case."
        )


def _load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return safe_load(f)


def main() -> None:
    # Ensure CWD is MANAGER so config relative paths resolve correctly
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)

    # Structured logging consistent with the rest of the project
    configure_logging()
    logger.info(
        "Starting Triton Client Manager in DEV mode",
        extra={"client_uuid": "-", "job_id": "-", "job_type": "dev_startup"},
    )

    # Load minimal configuration needed for dev
    config_job = _load_yaml(os.path.join("config", "jobs.yaml"))
    config_ws = _load_yaml(os.path.join("config", "websocket.yaml"))

    # Dummy backends (no real OpenStack/Docker/Triton)
    docker_backend = DevBackend(name="DockerDevBackend")
    openstack_backend = DevBackend(name="OpenstackDevBackend")
    triton_backend = DevBackend(name="TritonDevBackend")

    # Wire JobThread and WebSocketThread
    job = JobThread(**config_job)
    job.docker = docker_backend
    job.openstack = openstack_backend
    job.triton = triton_backend

    ws_cfg = dict(config_ws)
    auth_cfg = ws_cfg.pop("auth", None)
    rate_cfg = ws_cfg.pop("rate_limits", None)

    websocket = WebSocketThread(
        **ws_cfg,
        on_message=job.on_message,
        get_queue_stats=job.get_queue_stats,
    )
    if auth_cfg or rate_cfg:
        websocket.set_auth_and_rate_limits(
            auth_config=auth_cfg,
            rate_limit_config=rate_cfg,
        )
    job.websocket = websocket.send_to_client

    # Start threads
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
