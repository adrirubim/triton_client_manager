from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.openstack import OpenstackThread

class JobDeleteVM:
    def __init__(self, openstack: "OpenstackThread"):
        self.openstack = openstack

    def handle(self, msg_uuid: str, payload: dict) -> str:
        print(f"[Deletion-{msg_uuid}] Deleting OpenStack VM...")

        self.openstack.delete_vm(payload)

        print(f"[Deletion-{msg_uuid}] ✓ VM deleted: {payload['vm_id']}")
        return 