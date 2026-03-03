import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from classes.job.joberrors import JobContainerCreationFailed

if TYPE_CHECKING:
    from classes.docker import DockerThread


class JobCreateContainer:
    def __init__(self, docker: "DockerThread"):
        self.docker = docker

    def handle(self, msg_uuid: str, payload: dict, vm_ip: str = None) -> tuple:
        print(f"[Creation-{msg_uuid}] Step 2: Creating Docker container...")

        # --- Extrapolate DOCKER Data ---
        docker_config: dict = payload.get("docker", {})
        docker_config["worker_ip"] = vm_ip if vm_ip else payload.get("openstack", {}).get("vm_ip")

        # --- Random container name if needed ---
        if not docker_config.get("name"):
            docker_config["name"] = str(uuid.uuid4())

        # --- Extrapolate MINIO data ---
        minio_config = payload.get("minio", {})
        if minio_config:

            # --- Model repository ---
            parsed = urlparse(minio_config["endpoint"])
            s3_url = f"s3://{parsed.netloc}/{minio_config['bucket']}/{minio_config['folder']}"

            # --- Create server start command ---
            cmd = [a for a in docker_config.get("command", []) if not a.startswith("--model-repository=")]
            docker_config["command"] = cmd + [f"--model-repository={s3_url}"]

            # --- Environments to access MINIO ---
            docker_config.setdefault("environment", {})
            docker_config["environment"]["AWS_ACCESS_KEY_ID"]     = minio_config["access_key"]
            docker_config["environment"]["AWS_SECRET_ACCESS_KEY"] = minio_config["secret_key"]
            docker_config["environment"].setdefault("AWS_DEFAULT_REGION", "us-east-1")

        # --- Port mappings ---
        ports_config = docker_config.get("ports", {})
        docker_config["ports"] = {ports_config.get(8000, 8000): 8000,
                                  ports_config.get(8001, 8001): 8001,
                                  ports_config.get(8002, 8002): 8002}

        # --- Create container ---
        container_id = self.docker.create_container(docker_config)

        # --- Catch ---
        if not container_id:
            raise JobContainerCreationFailed("create_container() returned None")

        print(f"[Creation-{msg_uuid}] ✓ Container created: {container_id[:12]}")
        return container_id, docker_config
