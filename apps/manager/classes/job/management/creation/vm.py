import logging
from typing import TYPE_CHECKING

from classes.job.joberrors import JobVMCreationFailed

if TYPE_CHECKING:
    from classes.openstack import OpenstackThread

logger = logging.getLogger(__name__)


class JobCreateVM:
    def __init__(self, openstack: "OpenstackThread"):
        self.openstack = openstack

    def handle(self, msg_uuid: str, payload: dict) -> tuple:
        logger.info(
            "Creation step 1: creating OpenStack VM",
            extra={"client_uuid": msg_uuid, "job_id": "-", "job_type": "management_create_vm"},
        )

        # --- Extrapolate Data ---
        openstack_config = payload.get("openstack", {})

        # --- Create VM ---
        vm_ip, vm_id = self.openstack.create_vm(openstack_config)

        # --- Catch ---
        if not vm_ip or not vm_id:
            raise JobVMCreationFailed("create_vm() returned None")

        logger.info(
            "Creation step 1 complete: VM created",
            extra={
                "client_uuid": msg_uuid,
                "job_id": "-",
                "job_type": "management_create_vm",
                "vm_id": vm_id,
                "vm_ip": vm_ip,
            },
        )
        return vm_ip, vm_id
