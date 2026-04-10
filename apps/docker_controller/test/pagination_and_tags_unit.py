#!/usr/bin/env python3
"""
Unit-style tests for GitLab pagination header parsing + tag selection.
Run:
  python3 apps/docker_controller/test/pagination_and_tags_unit.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load(module_relpath: str, module_name: str):
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "apps" / "docker_controller" / module_relpath
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    # Ensure dataclasses (and others) can resolve module by name during exec.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_P = _load("gitlab_pagination.py", "gitlab_pagination")
_T = _load("tag_selection.py", "tag_selection")


def test_next_page_from_headers() -> None:
    assert _P.next_page_from_headers({"X-Next-Page": ""}) is None
    assert _P.next_page_from_headers({"X-Next-Page": "  "}) is None
    assert _P.next_page_from_headers({"X-Next-Page": "2"}) == 2
    assert _P.next_page_from_headers({"X-Next-Page": "0"}) is None
    assert _P.next_page_from_headers({"X-Next-Page": "nope"}) is None


def test_choose_tag_updated_at() -> None:
    tags = [
        {"name": "old", "updated_at": "2026-01-01T00:00:00Z"},
        {"name": "new", "updated_at": "2026-02-01T00:00:00Z"},
    ]
    assert _T.choose_tag_name(tags=tags, strategy="updated_at") == "new"


def test_choose_tag_created_at_with_regex_filter() -> None:
    tags = [
        {"name": "dev-1", "created_at": "2026-01-01T00:00:00Z"},
        {"name": "prod-1", "created_at": "2026-01-02T00:00:00Z"},
        {"name": "prod-2", "created_at": "2026-01-03T00:00:00Z"},
    ]
    assert (
        _T.choose_tag_name(tags=tags, strategy="created_at", name_regex="^prod-")
        == "prod-2"
    )


def test_choose_tag_empty() -> None:
    assert _T.choose_tag_name(tags=[], strategy="updated_at") is None


def main() -> None:
    test_next_page_from_headers()
    test_choose_tag_updated_at()
    test_choose_tag_created_at_with_regex_filter()
    test_choose_tag_empty()
    print("[OK] pagination_and_tags_unit.py")


if __name__ == "__main__":
    main()

