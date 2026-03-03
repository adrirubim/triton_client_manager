from typing import TYPE_CHECKING

from classes.job.joberrors import JobDeletionFailed, JobDeletionMissingField

from .container import JobDeleteContainer
from .server import JobDeleteServer
from .vm import JobDeleteVM

if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.openstack import OpenstackThread
    from classes.triton import TritonThread


class JobDeletion:
    def __init__(
        self, triton: "TritonThread", docker: "DockerThread", openstack: "OpenstackThread"
    ):

        self._vm = JobDeleteVM(openstack)
        self._container = JobDeleteContainer(docker)
        self._triton = JobDeleteServer(triton)

    def handle(self, msg_uuid: str, payload: dict) -> dict:
        """Best-effort deletion: run all 3 steps, collect failures, report at end."""
        errors = []

        # --- Check ---
        if "vm_id" not in payload:
            raise JobDeletionMissingField("vm_id")
        if "container_id" not in payload:
            raise JobDeletionMissingField("container_id")

        # --- Delete server ---
        try:
            self._triton.handle(msg_uuid, payload)
        except Exception as e:
            print(f"[Deletion-{msg_uuid}] ⚠ Triton delete_server failed (continuing): {e}")
            errors.append(f"triton_delete_server: {e}")

        # --- Delete container ---
        try:
            self._container.handle(msg_uuid, payload)
        except Exception as e:
            print(f"[Deletion-{msg_uuid}] ⚠ Delete container failed (continuing): {e}")
            errors.append(f"delete_container: {e}")

        # --- Delete VM ---
        try:
            self._vm.handle(msg_uuid, payload)
        except Exception as e:
            print(f"[Deletion-{msg_uuid}] ⚠ Delete VM failed: {e}")
            errors.append(f"delete_vm: {e}")

        # --- Raise ---
        if errors:
            raise JobDeletionFailed("; ".join(errors))

        return {"vm_id": payload["vm_id"], "container_id": payload["container_id"]}
