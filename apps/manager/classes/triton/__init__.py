from __future__ import annotations

import os
import sys

# Ensure repo root is importable so `import src.*` works when `apps/manager` is
# executed as a standalone entrypoint (e.g. CI running `python -m unittest` with
# `working-directory: apps/manager`).
_here = os.path.dirname(os.path.abspath(__file__))
# __file__ = <repo>/apps/manager/classes/triton/__init__.py
# We need <repo> on sys.path so `import src.*` works when CI runs from apps/manager.
_repo_root = os.path.abspath(os.path.join(_here, "..", "..", "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from .infer import TritonInfer  # noqa: E402
from .info.data.server import TritonServer  # noqa: E402
from .info.info import TritonInfo  # noqa: E402
from .tritonthread import TritonThread  # noqa: E402
