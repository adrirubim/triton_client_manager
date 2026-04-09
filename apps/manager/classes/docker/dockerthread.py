import logging
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional

import docker
from utils.metrics import observe_backend_error

from .creation import DockerCreation
from .deletion import DockerDeletion
from .dockererrors import (
    DockerAPIError,
    DockerContainerStateChanged,
    DockerCreationMissingField,
    DockerImageNotFound,
    DockerMissingArgument,
    DockerMissingContainer,
)
from .info import DockerInfo

if TYPE_CHECKING:
    from ..openstack import OpenstackThread


logger = logging.getLogger(__name__)

###################################
#        Docker Thread            #
###################################


class DockerThread(threading.Thread):
    def __init__(self, config):
        super().__init__(name="Docker_Thread", daemon=True)
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._data_lock = threading.Lock()

        # --- Loop ---
        self.refresh_time = config["refresh_time"]

        # --- Data ---
        self.dict_images = {}
        self.dict_containers = {}  # {container_id: Container}

        # Dependencies (set by ClientManager)
        self.openstack: OpenstackThread = None

        # --- Handlers ---
        self.docker_info = DockerInfo(config)
        self.docker_creation = DockerCreation(config)
        self.docker_deletion = DockerDeletion(config)

        # --- WebSocket (set by ClientManager) ---
        self.websocket: Optional[Callable[[dict], bool]] = None

    def start(self):
        """Scan containers after the openstack"""
        self.load()
        self._ready_event.set()  # Signal that initial load is complete
        super().start()

    def wait_until_ready(self, timeout=30):
        """Wait for initial load to complete"""
        return self._ready_event.wait(timeout)

    def stop(self):
        logger.info("[DockerThread] Stopping...")
        self._stop_event.set()

    def run(self):
        logger.info("[DockerThread] Started")

        while not self._stop_event.is_set():
            try:
                self.load()
                time.sleep(self.refresh_time)

            except Exception as e:
                observe_backend_error("docker")
                logger.exception("DockerThread main loop error: %s", e)

        logger.info("[DockerThread] Stopped")

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
                logger.warning("Failed to send Docker alert: %s", e)

    def load(self) -> None:
        with self._data_lock:
            self.dict_images = self.docker_info.load_images()

        if self.openstack:
            new_containers = self.docker_info.load_containers(self.openstack.dict_vms)

            with self._data_lock:
                for container_id, new_container in new_containers.items():
                    if container_id in self.dict_containers:
                        old_container = self.dict_containers[container_id]
                        has_changed, changed_fields = new_container.has_changed(old_container)

                        if has_changed:
                            error = DockerContainerStateChanged(
                                container_id,
                                new_container.name,
                                new_container.worker_ip,
                                changed_fields,
                            )
                            self._send_alert(error)

                self.dict_containers = new_containers

    def create_container(self, data: dict) -> str:
        # --- Validation ---
        if "image" not in data:
            raise DockerCreationMissingField("image")
        if "worker_ip" not in data:
            raise DockerCreationMissingField("worker_ip")

        image = data.pop("image")
        worker_ip = data.pop("worker_ip")

        # --- Creation ---
        try:
            container_id = self.docker_creation.handle(worker_ip, image, **data)
        except docker.errors.ImageNotFound:
            raise DockerImageNotFound(image)
        except docker.errors.APIError as e:
            raise DockerAPIError(str(e))

        # --- Refresh List ---
        if container_id and self.openstack:
            container = self.docker_info.load_single_container(worker_ip, container_id)
            with self._data_lock:
                self.dict_containers[container_id] = container

        return container_id

    def delete_container(self, data: dict) -> bool:
        # --- Check ---
        if "vm_id" not in data:
            raise DockerMissingArgument("vm_id")
        if "container_id" not in data:
            raise DockerMissingArgument("container_id")

        force = data.get("force", False)
        container_id = data["container_id"]
        remove_volumes = data.get("remove_volumes", False)

        # --- Retrieve IP ---
        with self._data_lock:
            if container_id in self.dict_containers:
                vm_ip = self.dict_containers[container_id].worker_ip
            else:
                raise DockerMissingContainer(container_id)

        # --- Delete ---
        self.docker_deletion.handle(
            ip=vm_ip,
            force=force,
            container_id=container_id,
            remove_volumes=remove_volumes,
        )

        # --- Remove ---
        with self._data_lock:
            self.dict_containers.pop(container_id, None)

        # --- Return payload ---
        return data
