import logging
from typing import TYPE_CHECKING

from utils.config_env import overlay_minio_payload

if TYPE_CHECKING:
    from classes.triton import TritonThread

logger = logging.getLogger(__name__)


class JobCreateServer:
    def __init__(self, triton: "TritonThread"):
        self.triton = triton

    def handle(
        self, msg_uuid: str, payload: dict, vm_id=None, vm_ip=None, container_id=None
    ) -> dict:
        logger.info(
            "Creation step 3: creating Triton server",
            extra={
                "client_uuid": msg_uuid,
                "job_id": "-",
                "job_type": "management_create_server",
            },
        )

        # --- Create payload ---
        data = {
            "vm_id": (
                vm_id
                if vm_id
                else payload.get("vm_id") or payload.get("openstack", {}).get("vm_id")
            ),
            "vm_ip": (
                vm_ip
                if vm_ip
                else payload.get("vm_ip") or payload.get("openstack", {}).get("vm_ip")
            ),
            "minio": overlay_minio_payload(payload.get("minio", {}) or {}),
            "triton": payload.get("triton", {}),
            "container_id": (
                container_id
                if container_id
                else payload.get("container_id")
                or payload.get("docker", {}).get("container_id")
            ),
        }

        # --- Create server ---
        server = self.triton.create_server(data)

        logger.info(
            "Creation step 3 complete: Triton server ready",
            extra={
                "client_uuid": msg_uuid,
                "job_id": "-",
                "job_type": "management_create_server",
                "model_name": server.model_name,
            },
        )
        return {
            "model_name": server.model_name,
            "inputs": server.inputs,
            "outputs": server.outputs,
        }
