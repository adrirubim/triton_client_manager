from __future__ import annotations

import os

import pytest
import requests


@pytest.fixture(scope="session")
def registry_url() -> str:
    # Allow override for CI / local setups
    return os.getenv("TCM_LOCAL_REGISTRY", "localhost:5000")


@pytest.fixture(scope="session")
def repositories(registry_url: str) -> list[str]:
    """
    Best-effort list of repositories from the local Docker registry.
    These tests are informational; if the registry isn't reachable, return [].
    """
    try:
        resp = requests.get(f"http://{registry_url}/v2/_catalog", timeout=5)
        resp.raise_for_status()
        payload = resp.json()
        repos = payload.get("repositories", [])
        return [r for r in repos if isinstance(r, str)]
    except Exception:
        return []

