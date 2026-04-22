"""
Domain package `tcm` for Triton Client Manager.

In this iteration it acts as a thin wrapper over `classes.*` to preserve
compatibility while the structure migration is completed.
"""

from .docker import *  # noqa: F401,F403
from .job import *  # noqa: F401,F403
from .openstack import *  # noqa: F401,F403
from .triton import *  # noqa: F401,F403
from .websocket import *  # noqa: F401,F403

# Canonical release tag (human-facing). This is the string used for git tags and docs.
RELEASE_VERSION = "v2.0.0-GOLDEN"
