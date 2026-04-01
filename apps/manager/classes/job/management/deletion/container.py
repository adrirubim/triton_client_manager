import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.docker import DockerThread

logger = logging.getLogger(__name__)


class JobDeleteContainer:
    def __init__(self, docker: "DockerThread"):
        self.docker = docker

    def handle(self, msg_uuid: str, payload: dict) -> str:
        logger.info(
            "Deletion step: deleting Docker container",
            extra={"client_uuid": msg_uuid, "job_id": "-", "job_type": "management_delete_container"},
        )

        # --- Execute ---
        self.docker.delete_container(payload)

        logger.info(
            "Deletion step complete: container deleted",
            extra={
                "client_uuid": msg_uuid,
                "job_id": "-",
                "job_type": "management_delete_container",
                "container_id": payload.get("container_id"),
            },
        )
        return payload
