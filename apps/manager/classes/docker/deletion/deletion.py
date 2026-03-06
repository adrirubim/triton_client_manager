import logging

import docker
from classes.docker.dockererrors import DockerDeletionError
from docker.errors import APIError, NotFound

logger = logging.getLogger(__name__)


class DockerDeletion:
    """Handles Docker container deletion via Docker SDK"""

    def __init__(self, config):
        self.remote_api_timeout = config.get("remote_api_timeout", 5)
        self.remote_api_port = config.get("remote_api_port", 2376)

    def handle(self, ip: str, force: bool, container_id: str, remove_volumes: bool):

        # --- Docker client ---
        client = None

        try:
            # --- Connect ---
            client = docker.DockerClient(
                base_url=f"tcp://{ip}:{self.remote_api_port}",
                timeout=self.remote_api_timeout,
            )
            # --- Get ---
            container = client.containers.get(container_id)

            # --- Stop ---
            if container.status == "running":
                logger.info("Stopping container")

                if force:
                    container.kill()
                else:
                    container.stop(timeout=10)

            # --- Remove ---
            logger.info("Removing container")
            container.remove(v=remove_volumes, force=force)

            logger.info("Container deleted successfully")

        except NotFound as e:
            raise DockerDeletionError(e)
        except APIError as e:
            raise DockerDeletionError(e)
        except Exception as e:
            raise DockerDeletionError(e)

        # --- Close connection ---
        finally:
            if client:
                client.close()
