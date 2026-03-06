from typing import TYPE_CHECKING

from classes.job.joberrors import JobVMCreationFailed

if TYPE_CHECKING:
    from classes.openstack import OpenstackThread


class JobCreateVM:
    def __init__(self, openstack: "OpenstackThread"):
        self.openstack = openstack

    def handle(self, msg_uuid: str, payload: dict) -> tuple:
        print(f"[Creation-{msg_uuid}] Step 1: Creating OpenStack VM...")

        # --- Extrapolate Data ---
        openstack_config = payload.get("openstack", {})

        # --- Create VM ---
        vm_ip, vm_id = self.openstack.create_vm(openstack_config)

        # --- Catch ---
        if not vm_ip or not vm_id:
            raise JobVMCreationFailed("create_vm() returned None")

        print(f"[Creation-{msg_uuid}] ✓ VM created: {vm_id} @ {vm_ip}")
        return vm_ip, vm_id
