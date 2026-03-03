from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

###################################
#       Triton Deletion           #
###################################
if TYPE_CHECKING:
    from  tritonclient.grpc import InferenceServerClient as grpc
    from  tritonclient.http import InferenceServerClient as http

class TritonDeletion:
    """Handles unloading models from Triton."""

    def handle(self, client: http|grpc, model_name: str) -> bool:
        try:
            client.unload_model(model_name)
            logger.info(" Unload request sent for model '{model_name}'")
            return True
        except Exception as e:
            logger.info(" Failed to unload model '{model_name}': {e}")
            return False
