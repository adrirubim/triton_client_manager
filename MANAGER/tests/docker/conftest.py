"""
Pytest fixtures for Docker test suite.
"""

import os
import yaml
from dataclasses import dataclass
from typing import Optional

import pytest


@dataclass
class MockVM:
    """Mock VM to simulate OpenStack VM structure."""

    id: str
    name: str
    address_private: Optional[str]


@pytest.fixture
def config():
    """Load configuration from docker.yaml"""
    config_path = os.path.join(os.path.dirname(__file__), "../../config/docker.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def mock_vms():
    """Mock VMs for container discovery and lifecycle tests."""
    return {"vm-001": MockVM(id="vm-001", name="docker-worker-1", address_private="10.50.0.234")}
