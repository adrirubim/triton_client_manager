from __future__ import annotations

import importlib
from unittest import mock

"""
Lightweight coverage test for client_manager entrypoint.

The goal is to ensure that importing client_manager (and thus calling
configure_logging at module level in main()) does not raise, without
starting real threads or touching external services.
"""


def test_client_manager_import_does_not_start_threads_or_crash():
    with mock.patch("client_manager.DockerThread"), mock.patch(
        "client_manager.JobThread"
    ), mock.patch("client_manager.OpenstackThread"), mock.patch(
        "client_manager.TritonThread"
    ), mock.patch(
        "client_manager.WebSocketThread"
    ), mock.patch(
        "client_manager.configure_logging"
    ):
        # Importing the module should succeed and expose ClientManager + main
        module = importlib.import_module("client_manager")
        assert hasattr(module, "ClientManager")
        assert hasattr(module, "main")
