import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.openstack import OpenstackThread

logger = logging.getLogger(__name__)


class JobDeleteVM:
    def __init__(self, openstack: "OpenstackThread"):
        self.openstack = openstack

    def handle(self, msg_uuid: str, payload: dict) -> str:
        logger.info(
            "Deletion step: deleting OpenStack VM",
            extra={"client_uuid": msg_uuid, "job_id": "-", "job_type": "management_delete_vm"},
        )

        self.openstack.delete_vm(payload)

        logger.info(
            "Deletion step complete: VM deleted",
            extra={
                "client_uuid": msg_uuid,
                "job_id": "-",
                "job_type": "management_delete_vm",
                "vm_id": payload.get("vm_id"),
            },
        )
        return
