import logging

logger = logging.getLogger(__name__)

import time

import tritonclient.http as httpclient

from ..constants import HTTP_PORT

###################################
#      Triton Info Handler        #
###################################


class TritonInfo:
    """Handles Triton Inference Server health checks, model load/unload, and metadata."""

    def __init__(self, timeout: int = 5, http_port: int = HTTP_PORT):
        self.timeout = timeout
        self.http_port = http_port

    def _client(
        self, vm_ip: str, timeout: int = None
    ) -> httpclient.InferenceServerClient:
        t = timeout if timeout is not None else self.timeout
        return httpclient.InferenceServerClient(
            url=f"{vm_ip}:{self.http_port}",
            connection_timeout=t,
            network_timeout=t,
        )

    # -------------------------------------------- #
    #              HEALTH CHECKS                   #
    # -------------------------------------------- #
    def is_server_ready(self, vm_ip: str) -> bool:
        try:
            return self._client(vm_ip).is_server_ready()
        except Exception:
            return False

    def is_model_ready(self, vm_ip: str, model_name: str) -> bool:
        try:
            return self._client(vm_ip).is_model_ready(model_name)
        except Exception:
            return False

    def wait_for_server_ready(self, vm_ip: str, timeout: int = 60) -> bool:
        start = time.time()
        while (time.time() - start) < timeout:
            if self.is_server_ready(vm_ip):
                logger.info(" Server ready at %s:%s", vm_ip, self.http_port)
                return True
            time.sleep(2)
        return False

    def wait_for_model_ready(
        self, vm_ip: str, model_name: str, timeout: int = 120
    ) -> bool:
        start = time.time()
        while (time.time() - start) < timeout:
            if self.is_model_ready(vm_ip, model_name):
                logger.info(" Model '{model_name}' is ready")
                return True
            time.sleep(3)
        return False

    # -------------------------------------------- #
    #           MODEL MANAGEMENT                   #
    # -------------------------------------------- #
    def load_model(
        self, vm_ip: str, model_name: str, timeout: int = 30, config_json: str = None
    ) -> bool:
        try:
            self._client(vm_ip, timeout=timeout).load_model(
                model_name, config=config_json
            )
            logger.info(" Load request sent for model '{model_name}'")
            return True
        except Exception as e:
            logger.info(" Failed to load model '%s': %s", model_name, e)
            return False

    def unload_model(self, vm_ip: str, model_name: str, timeout: int = 30) -> bool:
        try:
            self._client(vm_ip, timeout=timeout).unload_model(model_name)
            logger.info(" Unload request sent for model '{model_name}'")
            return True
        except Exception as e:
            logger.info(" Failed to unload model '%s': %s", model_name, e)
            return False

    # -------------------------------------------- #
    #               METADATA                       #
    # -------------------------------------------- #
    def get_server_metadata(self, vm_ip: str) -> dict:
        try:
            return self._client(vm_ip).get_server_metadata()
        except Exception as e:
            logger.info(" Failed to get server metadata: %s", e)
            return {}

    def get_model_metadata(self, vm_ip: str, model_name: str) -> dict:
        try:
            return self._client(vm_ip).get_model_metadata(model_name)
        except Exception as e:
            logger.info(" Failed to get model metadata: %s", e)
            return {}
