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
