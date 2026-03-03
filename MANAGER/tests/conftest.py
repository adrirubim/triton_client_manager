"""
Pytest configuration and fixtures for Triton Client Manager tests.
"""

import os
import sys

# Add MANAGER to path when running pytest from project root or MANAGER
_here = os.path.dirname(os.path.abspath(__file__))
_manager = os.path.join(_here, "..")
for p in (_manager, _here):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest


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
    from classes.websocket import WebSocketThread
    from classes.job import JobThread

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

    ws = WebSocketThread(**config_ws, on_message=job.on_message)
    job.websocket = ws.send_to_client

    job.start()
    ws.start()

    if not job.wait_until_ready(5):
        pytest.fail("JobThread failed to initialize")
    if not ws.wait_until_ready(10):
        pytest.fail("WebSocket failed to initialize")

    port = config_ws["port"]
    uri = f"ws://127.0.0.1:{port}/ws"

    yield uri

    job.stop()
    ws.stop()
    ws.join(timeout=5)


def pytest_configure(config):
    """Ensure tests run from MANAGER directory."""
    os.chdir(_manager)
