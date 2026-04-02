import logging
import threading
import time
from typing import Callable, Optional

from utils.metrics import observe_backend_error

from .creation.creation import TritonCreation
from .deletion.deletion import TritonDeletion
from .info.data.server import TritonServer
from .info.info import TritonInfo
from .tritonerrors import (
    TritonMissingArgument,
    TritonMissingInstance,
    TritonServerStateChanged,
)

logger = logging.getLogger(__name__)

###################################
#        Triton Thread            #
###################################


class TritonThread(threading.Thread):
    def __init__(self, config: dict):
        super().__init__(name="Triton_Thread", daemon=True)
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._data_lock = threading.Lock()

        # --- Loop ---
        self.refresh_time = config["refresh_time"]

        # --- Data ---
        self.dict_servers: dict[tuple, TritonServer] = (
            {}
        )  # {(vm_id, container_id): TritonServer}

        # --- Handlers ---
        self.triton_info = TritonInfo(timeout=config["health_check_timeout"])
        self.triton_creation = TritonCreation(config)
        self.triton_deletion = TritonDeletion()

        # --- WebSocket (set by ClientManager) ---
        self.websocket: Optional[Callable[[dict], bool]] = None

    def start(self):
        self.load()
        self._ready_event.set()
        super().start()

    def wait_until_ready(self, timeout: int = 30) -> bool:
        return self._ready_event.wait(timeout)

    def stop(self):
        logger.info("[TritonThread] Stopping...")
        self._stop_event.set()

    def run(self):
        logger.info("[TritonThread] Started")
        while not self._stop_event.is_set():
            try:
                self.load()
                time.sleep(self.refresh_time)
            except Exception as e:
                observe_backend_error("triton")
                logger.info(" TritonThread main loop: %s", e)
        logger.info("[TritonThread] Stopped")

    def _send_alert(self, error: Exception):
        if self.websocket:
            try:
                alert_payload = {
                    "type": "alert",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "timestamp": time.time(),
                }
                self.websocket(alert_payload)
            except Exception as e:
                logger.info(" TritonThread failed to send alert: %s", e)

    def load(self) -> None:
        """Health-check all known servers; detect and alert on status changes."""

        # --- Copy ---
        with self._data_lock:
            servers = dict(self.dict_servers)

        # --- Iter throght ---
        for (vm_id, container_id), server in servers.items():
            try:
                # --- Check Health Server ---
                healthy = self.triton_info.is_server_ready(server.vm_ip)
                new_status = "ready" if healthy else "unhealthy"

                # --- Change Healthy -> Unhealthy ---
                if new_status != server.status:
                    old_status = server.status
                    server.status = new_status

                    # --- Send Alert --
                    self._send_alert(
                        TritonServerStateChanged(
                            server.vm_ip,
                            container_id,
                            [f"status: {old_status} -> {new_status}"],
                        )
                    )
            except Exception:
                observe_backend_error("triton")
                logger.info(
                    " Health check failed for ({vm_id}, {container_id[:12]}): {e}"
                )

    # -------------------------------------------- #
    #               LIFECYCLE                      #
    # -------------------------------------------- #

    def create_server(self, data: dict) -> TritonServer:
        """Create a TritonServer (wait, load model, build clients) and register it."""

        # --- Check ---
        if "vm_id" not in data:
            raise TritonMissingArgument("vm_id")
        if "vm_ip" not in data:
            raise TritonMissingArgument("vm_ip")
        if "minio" not in data:
            raise TritonMissingArgument("minio")
        if "container_id" not in data:
            raise TritonMissingArgument("container_id")

        # --- Optional ---
        data["triton"] = data.get("triton", {})

        # --- Create Server ---
        server = self.triton_creation.handle(**data)

        # --- Replace Dead ---
        with self._data_lock:
            existing = self.dict_servers.get((data["vm_id"], data["container_id"]))
            if existing:
                existing.close()
            self.dict_servers[(data["vm_id"], data["container_id"])] = server

        return server

    def delete_server(self, data: dict) -> None:
        """Unload all models on the server, close clients, and deregister."""

        # --- Catch ---
        if "vm_id" not in data:
            raise TritonMissingArgument("vm_id")
        if "container_id" not in data:
            raise TritonMissingArgument("container_id")

        vm_id = data["vm_id"]
        container_id = data["container_id"]

        # --- Fetch ---
        with self._data_lock:
            server = self.dict_servers.get((vm_id, container_id))

        # --- Delete ---
        if server:
            self.triton_deletion.handle(server.client, server.model_name)
            server.close()
        else:
            raise TritonMissingInstance(vm_id, container_id)

        # --- Remove ---
        with self._data_lock:
            self.dict_servers.pop((vm_id, container_id), None)

        logger.info(" Deregistered ({vm_id}, {container_id[:12]})")
        return data
