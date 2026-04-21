"""
Compatibility package.

Historically `apps/manager` was used as the working directory, so imports like
`utils.auth` resolved naturally.

When running from repo root, this package provides a stable alias so that:
  - `import utils` behaves like `import apps.manager.utils`
  - `import utils.<module>` behaves like `import apps.manager.utils.<module>`
"""

from __future__ import annotations

import importlib
import sys

_pkg = importlib.import_module("apps.manager.utils")
sys.modules[__name__] = _pkg

# Common utility modules used across the codebase/tests.
for _name in (
    "auth",
    "bounded_executor",
    "config_env",
    "log_safety",
    "logging_config",
    "metrics",
    "stream_cancel",
):
    try:
        _sub = importlib.import_module(f"apps.manager.utils.{_name}")
        sys.modules[f"{__name__}.{_name}"] = _sub
    except Exception:
        pass

