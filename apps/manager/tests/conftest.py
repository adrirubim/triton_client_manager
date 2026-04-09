"""
Pytest configuration and fixtures for Triton Client Manager tests.
"""

import os
import sys

import pytest

# Add apps/manager to path when running pytest from project root or apps/manager
_here = os.path.dirname(os.path.abspath(__file__))
_manager = os.path.join(_here, "..")
# Repository root: .../apps/manager -> .../ (two levels up)
_repo_root = os.path.abspath(os.path.join(_manager, "..", ".."))
for p in (_repo_root, _manager, _here):
    if p not in sys.path:
        sys.path.insert(0, p)


def _create_mock_thread(name, attrs=None):
    """Minimal mock thread for DI."""
    t = type(name, (), {})()
    for k, v in (attrs or {}).items():
        setattr(t, k, v)
    t.dict_containers = getattr(t, "dict_containers", {})
    t.dict_servers = getattr(t, "dict_servers", {})
    return t


@pytest.fixture(scope="session")
def ws_server():
    """
    Session-scoped fixture: starts JobThread + WebSocketThread (mocked backends),
    yields the WebSocket URI, then stops on teardown.
    """
    from yaml import safe_load

    from classes.job import JobThread
    from classes.websocket import WebSocketThread

    config_dir = os.path.join(_manager, "config")
    with open(os.path.join(config_dir, "jobs.yaml"), encoding="utf-8") as f:
        config_job = safe_load(f)
    with open(os.path.join(config_dir, "websocket.yaml"), encoding="utf-8") as f:
        config_ws = safe_load(f)

    mock_docker = _create_mock_thread("DockerThread", {"dict_containers": {}})
    mock_openstack = _create_mock_thread("OpenstackThread")
    mock_triton = _create_mock_thread("TritonThread", {"dict_servers": {}})

    job = JobThread(**config_job)
    job.docker = mock_docker
    job.openstack = mock_openstack
    job.triton = mock_triton
    job.websocket = None

    ws_cfg = dict(config_ws)
    auth_cfg = ws_cfg.pop("auth", None)
    rate_cfg = ws_cfg.pop("rate_limits", None)
    # Use a dynamic port to avoid collisions in CI / parallel runs.
    ws_cfg["port"] = 0

    ws = WebSocketThread(**ws_cfg, on_message=job.on_message, get_queue_stats=job.get_queue_stats)
    if auth_cfg or rate_cfg:
        ws.set_auth_and_rate_limits(auth_config=auth_cfg, rate_limit_config=rate_cfg)
    job.websocket = ws.send_to_client

    job.start()
    ws.start()

    if not job.wait_until_ready(5):
        pytest.fail("JobThread failed to initialize")
    if not ws.wait_until_ready(10):
        pytest.fail("WebSocket failed to initialize")

    # WebSocketThread captures the bound ephemeral port after startup.
    uri = f"ws://127.0.0.1:{ws.port}/ws"

    yield uri

    job.stop()
    ws.stop()
    ws.join(timeout=5)


def pytest_configure(config):
    """Ensure tests run from apps/manager directory."""
    os.chdir(_manager)
