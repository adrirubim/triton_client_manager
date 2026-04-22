from importlib.metadata import PackageNotFoundError, version

from .sdk import AuthContext, TcmWebSocketClient, quickstart_queue_stats, run_quickstart

__all__ = [
    "AuthContext",
    "TcmWebSocketClient",
    "quickstart_queue_stats",
    "run_quickstart",
    "__release__",
    "__version__",
]

# Canonical release tag (human-facing). This is the string used for git tags and docs.
__release__ = "v2.0.0-GOLDEN"

try:
    __version__ = version("tcm-client")
except PackageNotFoundError:
    # Repo checkout / editable-import scenario (package not installed).
    __version__ = "2.0.0"
