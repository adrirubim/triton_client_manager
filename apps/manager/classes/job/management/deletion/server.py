import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.triton import TritonThread

logger = logging.getLogger(__name__)


class JobDeleteServer:
    def __init__(self, triton: "TritonThread"):
        self.triton = triton

    def handle(self, msg_uuid: str, payload: dict) -> dict:
        logger.info(
            "Deletion step: deleting Triton server",
            extra={
                "client_uuid": msg_uuid,
                "job_id": "-",
                "job_type": "management_delete_server",
            },
        )

        # --- Execute ---
        self.triton.delete_server(payload)

        logger.info(
            "Deletion step complete: Triton server deregistered",
            extra={
                "client_uuid": msg_uuid,
                "job_id": "-",
                "job_type": "management_delete_server",
                "vm_id": payload.get("vm_id"),
                "container_id": payload.get("container_id"),
            },
        )
        return payload
