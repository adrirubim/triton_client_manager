from typing import TYPE_CHECKING

from .container import JobCreateContainer
from .server import JobCreateServer
from .vm import JobCreateVM

if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.openstack import OpenstackThread
    from classes.triton import TritonThread


class JobCreation:
    def __init__(
        self, triton: "TritonThread", docker: "DockerThread", openstack: "OpenstackThread"
    ):

        self._vm = JobCreateVM(openstack)
        self._container = JobCreateContainer(docker)
        self._triton = JobCreateServer(triton) if triton else None

    def handle(self, msg_uuid: str, payload: dict) -> dict:
        vm_id = None
        vm_ip = None
        container_id = None

        # ------------ Create VM ------------
        vm_ip, vm_id = self._vm.handle(msg_uuid, payload)

        # ------------ Create Container ------------
        try:
            container_id, _ = self._container.handle(msg_uuid, payload, vm_ip=vm_ip)
        except Exception:
            # --- Rollback VM on container creation failure ---
            if vm_id:
                self._vm.openstack.delete_vm(vm_id)
            raise

        # ------------ Create Server ------------
        try:
            result = self._triton.handle(
                msg_uuid, payload, vm_id=vm_id, vm_ip=vm_ip, container_id=container_id
            )
        except Exception:
            # --- Remove Error ---
            if container_id:
                self._container.docker.delete_container(
                    {
                        "worker_ip": vm_ip,
                        "container_id": container_id,
                        "force": True,
                    }
                )
            if vm_id:
                self._vm.openstack.delete_vm(vm_id)
            raise

        # ------------ Return Data For Inference ------------
        return {"vm_ip": vm_ip, "container_id": container_id, **result}
