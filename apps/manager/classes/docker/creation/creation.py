import logging

logger = logging.getLogger(__name__)


class DockerCreation:
    """Handles Docker container creation via Docker SDK"""

    def __init__(self, config):
        self.remote_api_timeout = config.get("remote_api_timeout", 5)
        self.remote_api_port = config.get("remote_api_port", 2376)
        self.registry_address = config.get("registry_address", "localhost:5000")

    def handle(self, worker_ip: str, image: str, **kwargs) -> str:
        import docker  # heavy import (lazy)

        client = None
        try:
            full_image = f"{self.registry_address}/{image}"
            logger.info("Using image: %s", full_image)

            base_url = f"tcp://{worker_ip}:{self.remote_api_port}"
            client = docker.DockerClient(base_url=base_url, timeout=self.remote_api_timeout)

            name = kwargs.get("name")
            command = kwargs.get("command")
            ports = kwargs.get("ports")
            environment = kwargs.get("environment")
            volumes = kwargs.get("volumes")
            detach = kwargs.get("detach", True)
            auto_remove = kwargs.get("auto_remove", False)
            restart_policy = kwargs.get("restart_policy")

            logger.debug("Creating container on %s", worker_ip)
            if name:
                logger.debug("Name: %s", name)

            container = client.containers.run(
                image=full_image,
                name=name,
                command=command,
                ports=ports,
                environment=environment,
                volumes=volumes,
                detach=detach,
                auto_remove=auto_remove,
                restart_policy=restart_policy,
            )

            container_id = container.id
            logger.debug("Container created: %s", container_id[:12])

            return container_id

        finally:
            if client:
                client.close()
