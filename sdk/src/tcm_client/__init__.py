from importlib.metadata import PackageNotFoundError, version

from .sdk import AuthContext, TcmWebSocketClient, quickstart_queue_stats, run_quickstart

__all__ = [
    "AuthContext",
    "TcmWebSocketClient",
    "quickstart_queue_stats",
    "run_quickstart",
    "__version__",
]

try:
    __version__ = version("tcm-client")
except PackageNotFoundError:
    # Repo checkout / editable-import scenario (package not installed).
    __version__ = "0.0.0"
