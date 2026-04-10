#!/usr/bin/env python3
"""
Unit-style tests for supply-chain guardrails (no external services).
Run:
  python3 apps/docker_controller/test/guardrails_unit.py
"""

from __future__ import annotations


import importlib.util
from pathlib import Path


def _load_guardrails_module():
    """
    Load apps/docker_controller/guardrails.py without requiring third-party deps.
    """

    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "apps" / "docker_controller" / "guardrails.py"

    spec = importlib.util.spec_from_file_location("docker_controller_guardrails", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec for {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_G = _load_guardrails_module()
_is_allowed_image = _G.is_allowed_image
_validate_supply_chain_guardrails = _G.validate_supply_chain_guardrails


def test_allowlist_by_image_name() -> None:
    allowed_images = {"image1"}
    allowed_regex = []
    assert _is_allowed_image(
        location="gitlab.example:5050/group/project/image1",
        allowed_images=allowed_images,
        allowed_regex=allowed_regex,
    )
    assert not _is_allowed_image(
        location="gitlab.example:5050/group/project/other",
        allowed_images=allowed_images,
        allowed_regex=allowed_regex,
    )


def test_guardrail_rejects_insecure_gitlab() -> None:
    cfg = {
        "provider": "gitlab",
        "gitlab_url": "http://gitlab.example",
        "allowed_images": ["image1"],
        "project_id": 1,
    }
    try:
        _validate_supply_chain_guardrails(
            config=cfg,
            local_registry_hostport="localhost:5000",
            local_registry_scheme="http",
        )
    except ValueError as e:
        assert "gitlab_url must start with 'https://'" in str(e)
    else:
        raise AssertionError("Expected ValueError for insecure gitlab_url")


def test_guardrail_rejects_nonlocal_registry_without_opt_in() -> None:
    cfg = {
        "provider": "gitlab",
        "gitlab_url": "https://gitlab.example",
        "allowed_images": ["image1"],
        "project_id": 1,
    }
    try:
        _validate_supply_chain_guardrails(
            config=cfg,
            local_registry_hostport="10.0.0.10:5000",
            local_registry_scheme="http",
        )
    except ValueError as e:
        assert "allow_nonlocal_registry=true" in str(e)
    else:
        raise AssertionError("Expected ValueError for non-local registry without opt-in")


def test_guardrail_requires_https_for_nonlocal_registry() -> None:
    cfg = {
        "provider": "gitlab",
        "gitlab_url": "https://gitlab.example",
        "allowed_images": ["image1"],
        "allow_nonlocal_registry": True,
        "project_id": 1,
    }
    try:
        _validate_supply_chain_guardrails(
            config=cfg,
            local_registry_hostport="10.0.0.10:5000",
            local_registry_scheme="http",
        )
    except ValueError as e:
        assert "local_registry_scheme=https" in str(e)
    else:
        raise AssertionError("Expected ValueError for non-local registry without https")


def main() -> None:
    test_allowlist_by_image_name()
    test_guardrail_rejects_insecure_gitlab()
    test_guardrail_rejects_nonlocal_registry_without_opt_in()
    test_guardrail_requires_https_for_nonlocal_registry()
    print("[OK] guardrails_unit.py")


if __name__ == "__main__":
    main()

