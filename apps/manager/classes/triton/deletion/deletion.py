from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

###################################
#       Triton Deletion           #
###################################
if TYPE_CHECKING:
    from tritonclient.grpc import InferenceServerClient as GrpcClient
    from tritonclient.http import InferenceServerClient as HttpClient


class TritonDeletion:
    """Handles unloading models from Triton."""

    def handle(self, client: "HttpClient | GrpcClient", model_name: str, *, timeout_seconds: int | None = None) -> bool:
        try:
            # Under explicit model-control-mode, unload_model is the expected lifecycle action.
            # Prefer using per-call timeouts when supported by the client implementation.
            if timeout_seconds is None:
                client.unload_model(model_name)
            else:
                try:
                    client.unload_model(model_name, client_timeout=int(timeout_seconds))
                except TypeError:
                    client.unload_model(model_name)
            logger.info(" Unload request sent for model '%s'", model_name)
            return True
        except Exception as e:
            logger.info(" Failed to unload model '%s': %s", model_name, e)
            return False
