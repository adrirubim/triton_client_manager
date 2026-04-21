"""
Compatibility package.

Historically `apps/manager` was used as the working directory, so imports like
`classes.triton...` resolved naturally.

When running from repo root, this package provides a stable alias so that:
  - `import classes` behaves like `import apps.manager.classes`
  - `import classes.<subpkg>` behaves like `import apps.manager.classes.<subpkg>`
"""

from __future__ import annotations

import importlib
import sys

# Alias the package itself.
_pkg = importlib.import_module("apps.manager.classes")
sys.modules[__name__] = _pkg

# Alias common subpackages so deep imports like `classes.docker.dockererrors` work.
for _name in ("docker", "job", "openstack", "triton", "websocket"):
    try:
        _sub = importlib.import_module(f"apps.manager.classes.{_name}")
        sys.modules[f"{__name__}.{_name}"] = _sub
    except Exception:
        # Best-effort only: importing should not explode if optional deps are missing.
        pass

