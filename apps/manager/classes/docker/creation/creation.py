import logging

import docker
from docker.tls import TLSConfig

logger = logging.getLogger(__name__)


class DockerCreation:
    """Handles Docker container creation via Docker SDK"""

    def __init__(self, config):
        self.remote_api_timeout = config.get("remote_api_timeout", 5)
        self.remote_api_port = config.get("remote_api_port", 2376)
        self.registry_address = config.get("registry_address", "localhost:5000")
        self.remote_api_scheme = (config.get("remote_api_scheme") or "http").lower()
        self.remote_api_tls_verify = config.get("remote_api_tls_verify", True)
        self.remote_api_ca_cert_path = config.get("remote_api_ca_cert_path")
        self.remote_api_client_cert_path = config.get("remote_api_client_cert_path")
        self.remote_api_client_key_path = config.get("remote_api_client_key_path")

    def _tls_config(self) -> TLSConfig | None:
        # Only enable TLS config for https or when explicit TLS material is provided.
        if self.remote_api_scheme != "https" and not (
            self.remote_api_ca_cert_path or self.remote_api_client_cert_path or self.remote_api_client_key_path
        ):
            return None

        ca_cert = self.remote_api_ca_cert_path
        if not ca_cert and self.remote_api_tls_verify:
            # Docker SDK allows verify=True with system CA bundle in some environments,
            # but for remote daemons it's usually a custom CA; keep it optional.
            ca_cert = None

        client_cert = None
        if self.remote_api_client_cert_path and self.remote_api_client_key_path:
            client_cert = (self.remote_api_client_cert_path, self.remote_api_client_key_path)

        if not (self.remote_api_tls_verify or ca_cert or client_cert):
            return None

        return TLSConfig(
            client_cert=client_cert,
            ca_cert=ca_cert,
            verify=bool(self.remote_api_tls_verify),
        )

    def handle(self, worker_ip: str, image: str, **kwargs) -> str:
        client = None
        try:
            full_image = f"{self.registry_address}/{image}"
            logger.info("Using image: %s", full_image)

            base_url = f"tcp://{worker_ip}:{self.remote_api_port}"
            tls = self._tls_config()
            if tls is None:
                client = docker.DockerClient(
                    base_url=base_url,
                    timeout=self.remote_api_timeout,
                )
            else:
                client = docker.DockerClient(
                    base_url=base_url,
                    timeout=self.remote_api_timeout,
                    tls=tls,
                )

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
