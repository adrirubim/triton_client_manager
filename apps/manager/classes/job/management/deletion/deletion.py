import logging
from typing import TYPE_CHECKING

from classes.job.joberrors import JobDeletionFailed, JobDeletionMissingField

from .container import JobDeleteContainer
from .server import JobDeleteServer
from .vm import JobDeleteVM

if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.openstack import OpenstackThread
    from classes.triton import TritonThread

logger = logging.getLogger(__name__)


class JobDeletion:
    def __init__(
        self,
        triton: "TritonThread",
        docker: "DockerThread",
        openstack: "OpenstackThread",
    ):

        self._vm = JobDeleteVM(openstack)
        self._container = JobDeleteContainer(docker)
        self._triton = JobDeleteServer(triton)

    def handle(self, msg_uuid: str, payload: dict) -> dict:
        """Best-effort deletion: run all 3 steps, collect failures, report at end."""
        errors = []

        # --- Normalize payload contract (support legacy nested keys) ---
        if "vm_id" not in payload:
            nested_vm_id = payload.get("openstack", {}).get("vm_id")
            if nested_vm_id:
                payload["vm_id"] = nested_vm_id
        if "container_id" not in payload:
            nested_container_id = payload.get("docker", {}).get("container_id")
            if nested_container_id:
                payload["container_id"] = nested_container_id

        # Best-effort: if vm_id is still missing but vm_ip is present, try to infer
        # the VM id from the OpenStack cache by matching address_public/address_private.
        if "vm_id" not in payload:
            vm_ip = payload.get("vm_ip") or payload.get("openstack", {}).get("vm_ip")
            if isinstance(vm_ip, str) and vm_ip:
                os_thread = getattr(self._vm, "openstack", None)
                candidates = []
                if os_thread and hasattr(os_thread, "dict_vms"):
                    for vm_id, vm in (os_thread.dict_vms or {}).items():
                        if (
                            getattr(vm, "address_public", None) == vm_ip
                            or getattr(vm, "address_private", None) == vm_ip
                        ):
                            candidates.append(vm_id)
                if len(candidates) == 1:
                    payload["vm_id"] = candidates[0]
                elif len(candidates) > 1:
                    logger.warning(
                        "Deletion payload vm_id ambiguous for vm_ip; refusing to infer",
                        extra={
                            "client_uuid": msg_uuid,
                            "job_id": "-",
                            "job_type": "management_deletion",
                            "vm_ip": vm_ip,
                        },
                    )

        # --- Check ---
        if "vm_id" not in payload:
            raise JobDeletionMissingField("vm_id")
        if "container_id" not in payload:
            raise JobDeletionMissingField("container_id")

        # --- Delete server ---
        try:
            self._triton.handle(msg_uuid, payload)
        except Exception as e:
            logger.warning(
                "Deletion step triton delete_server failed (continuing)",
                extra={
                    "client_uuid": msg_uuid,
                    "job_id": "-",
                    "job_type": "management_deletion",
                },
            )
            errors.append(f"triton_delete_server: {e}")

        # --- Delete container ---
        try:
            self._container.handle(msg_uuid, payload)
        except Exception as e:
            logger.warning(
                "Deletion step docker delete_container failed (continuing)",
                extra={
                    "client_uuid": msg_uuid,
                    "job_id": "-",
                    "job_type": "management_deletion",
                },
            )
            errors.append(f"delete_container: {e}")

        # --- Delete VM ---
        try:
            self._vm.handle(msg_uuid, payload)
        except Exception as e:
            logger.warning(
                "Deletion step openstack delete_vm failed",
                extra={
                    "client_uuid": msg_uuid,
                    "job_id": "-",
                    "job_type": "management_deletion",
                },
            )
            errors.append(f"delete_vm: {e}")

        # --- Raise ---
        if errors:
            raise JobDeletionFailed("; ".join(errors))

        return {"vm_id": payload["vm_id"], "container_id": payload["container_id"]}
