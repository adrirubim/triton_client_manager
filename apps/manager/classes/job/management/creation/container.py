import logging
import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pydantic import ValidationError
from src.Domains.Config.Schemas.RuntimeMinioPayload import RuntimeMinioPayload

from classes.job.joberrors import JobContainerCreationFailed
from utils.config_env import overlay_minio_payload

if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.openstack import OpenstackThread

logger = logging.getLogger(__name__)


class JobCreateContainer:
    def __init__(self, docker: "DockerThread", openstack: "OpenstackThread" = None):
        self.docker = docker
        self.openstack = openstack

    def _resolve_worker_ip(self, payload: dict) -> str:
        """
        Resolve worker IP from trusted internal state only.
        Never accept vm_ip/worker_ip from client payload to prevent SSRF.
        """
        # Preferred: resolve by vm_id from OpenStack cache.
        vm_id = (
            payload.get("vm_id")
            or (payload.get("openstack", {}) or {}).get("vm_id")
            or payload.get("openstack_vm_id")
        )
        if vm_id and self.openstack:
            vm = getattr(self.openstack, "dict_vms", {}).get(vm_id)
            vm_ip = getattr(vm, "address_private", None)
            if isinstance(vm_ip, str) and vm_ip:
                return vm_ip

        raise JobContainerCreationFailed(
            "Refusing to use client-supplied vm_ip/worker_ip. Provide a valid vm_id for a managed VM."
        )

    def handle(self, msg_uuid: str, payload: dict, vm_ip: str = None) -> tuple:
        logger.info(
            "Creation step 2: creating Docker container",
            extra={
                "client_uuid": msg_uuid,
                "job_id": "-",
                "job_type": "management_create_container",
            },
        )

        # --- Extrapolate DOCKER Data ---
        docker_config: dict = payload.get("docker", {})
        docker_config["worker_ip"] = self._resolve_worker_ip(payload)

        # --- Random container name if needed ---
        if not docker_config.get("name"):
            docker_config["name"] = str(uuid.uuid4())

        # --- Extrapolate MINIO data ---
        minio_config = overlay_minio_payload(payload.get("minio", {}) or {})
        if minio_config:
            try:
                minio_runtime = RuntimeMinioPayload.model_validate(minio_config)
            except ValidationError as exc:
                raise JobContainerCreationFailed(
                    f"Invalid MinIO payload (runtime): {exc}"
                ) from exc

            # --- Model repository ---
            parsed = urlparse(str(minio_runtime.endpoint))
            s3_url = (
                f"s3://{parsed.netloc}/{minio_runtime.bucket}/{minio_runtime.folder}"
            )

            # --- Create server start command ---
            cmd = [
                a
                for a in docker_config.get("command", [])
                if not a.startswith("--model-repository=")
            ]
            docker_config["command"] = cmd + [f"--model-repository={s3_url}"]

            # --- Environments to access MINIO ---
            docker_config.setdefault("environment", {})
            docker_config["environment"]["AWS_ACCESS_KEY_ID"] = minio_runtime.access_key
            docker_config["environment"][
                "AWS_SECRET_ACCESS_KEY"
            ] = minio_runtime.secret_key
            docker_config["environment"].setdefault(
                "AWS_DEFAULT_REGION",
                minio_config.get("region") or "us-east-1",
            )

        # --- Port mappings ---
        ports_config = docker_config.get("ports", {})
        docker_config["ports"] = {
            ports_config.get(8000, 8000): 8000,
            ports_config.get(8001, 8001): 8001,
            ports_config.get(8002, 8002): 8002,
        }

        # --- Create container ---
        container_id = self.docker.create_container(docker_config)

        # --- Catch ---
        if not container_id:
            raise JobContainerCreationFailed("create_container() returned None")

        logger.debug(
            "Creation step 2 complete: container created",
            extra={
                "client_uuid": msg_uuid,
                "job_id": "-",
                "job_type": "management_create_container",
                "container_id": container_id,
            },
        )
        return container_id, docker_config
