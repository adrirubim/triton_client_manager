import logging
from typing import Dict

import requests

logger = logging.getLogger(__name__)
from .data import Container, Image


class DockerInfo:
    """Handles Docker resource information loading"""

    def __init__(self, config):
        self.registry_timeout = config["registry_timeout"]
        self.registry_endpoint = config["registry_endpoint"]
        self.registry_image_types = config["registry_image_types"]
        self.remote_api_timeout = config.get("remote_api_timeout", 5)
        self.remote_api_port = config.get("remote_api_port", 2376)
        self.remote_api_scheme = (config.get("remote_api_scheme") or "http").lower()
        self.remote_api_tls_verify = config.get("remote_api_tls_verify", True)
        self.remote_api_ca_cert_path = config.get("remote_api_ca_cert_path")
        self.remote_api_client_cert_path = config.get("remote_api_client_cert_path")
        self.remote_api_client_key_path = config.get("remote_api_client_key_path")

        if self.remote_api_scheme not in {"http", "https"}:
            raise ValueError(f"Invalid remote_api_scheme={self.remote_api_scheme!r} (expected http|https)")

    def _remote_api_requests_kwargs(self) -> dict:
        if self.remote_api_scheme != "https":
            return {}

        kwargs: dict = {}
        if self.remote_api_ca_cert_path:
            kwargs["verify"] = self.remote_api_ca_cert_path
        else:
            kwargs["verify"] = bool(self.remote_api_tls_verify)

        if self.remote_api_client_cert_path and self.remote_api_client_key_path:
            kwargs["cert"] = (
                self.remote_api_client_cert_path,
                self.remote_api_client_key_path,
            )
        return kwargs

    def load_images(self) -> Dict[str, Image]:
        """
        Load Docker images from catalog registry

        Pipeline:
        1. GET /v2/_catalog to list repositories
        2. For each repo in catalog_image_types:
           - GET /v2/<repo>/tags/list to get tags
           - GET /v2/<repo>/manifests/<tag> to get details
        3. Parse and return dict[name:tag, Image]

        Returns:
            dict[str, Image]: Dictionary keyed by "name:tag"
        """
        images = {}

        try:
            # Step 1: Get registry catalog
            registry_url = f"{self.registry_endpoint}/v2/_catalog"
            response = requests.get(registry_url, timeout=self.registry_timeout)
            response.raise_for_status()
            registry_data = response.json()

            repositories = registry_data.get("repositories", [])

            # Step 2: Filter by configured types
            for repo in repositories:
                if repo not in self.registry_image_types:
                    continue

                # Step 3: Get tags for this repository
                tags_url = f"{self.registry_endpoint}/v2/{repo}/tags/list"
                tags_response = requests.get(tags_url, timeout=self.registry_timeout)
                tags_response.raise_for_status()
                tags_data = tags_response.json()

                # Step 4: Parse images using data class
                repo_images = Image.from_api(
                    {
                        "name": repo,
                        "tags": tags_data.get("tags", []),
                        "endpoint": self.registry_endpoint,
                    }
                )

                images.update(repo_images)

            logger.info("Loaded %d images from registry", len(images))
            return images

        except Exception as e:
            logger.exception("load_images: %s", e)
            return {}

    def load_containers(self, dict_vms: dict) -> Dict[str, Container]:
        """
        Load Docker containers from OpenStack VMs via Remote API

        Args:
            dict_vms: Dictionary of VM objects from OpenStack

        Returns:
            dict[str, Container]: Dictionary keyed by container ID
        """
        all_containers = {}

        try:
            for vm_id, vm in dict_vms.items():
                if not vm.address_private:
                    continue

                worker_ip = vm.address_private

                try:
                    api_url = f"{self.remote_api_scheme}://{worker_ip}:{self.remote_api_port}" "/containers/json"
                    response = requests.get(
                        api_url,
                        timeout=self.remote_api_timeout,
                        **self._remote_api_requests_kwargs(),
                    )
                    response.raise_for_status()
                    containers_data = response.json()

                    containers = Container.from_api(containers_data, worker_ip)
                    all_containers.update(containers)

                    logger.debug("Loaded %d containers from %s", len(containers), worker_ip)

                except requests.exceptions.RequestException as e:
                    logger.warning("Cannot reach worker %s: %s", worker_ip, e)
                    continue

            logger.info("Total containers loaded: %d", len(all_containers))
            return all_containers

        except Exception as e:
            logger.exception("load_containers: %s", e)
            return {}

    # --------------- HELPERS ---------------
    def get_container_ports(self, worker_ip: str, container_id: str) -> dict:
        try:
            api_url = (
                f"{self.remote_api_scheme}://{worker_ip}:{self.remote_api_port}" f"/containers/{container_id}/json"
            )
            response = requests.get(
                api_url,
                timeout=self.remote_api_timeout,
                **self._remote_api_requests_kwargs(),
            )
            response.raise_for_status()
            container_data = response.json()

            ports_data = container_data.get("NetworkSettings", {}).get("Ports", {})
            port_mappings = {}

            for container_port, host_bindings in ports_data.items():
                if host_bindings:
                    port_num = int(container_port.split("/")[0])
                    host_port = int(host_bindings[0].get("HostPort"))
                    port_mappings[port_num] = host_port

            return port_mappings

        except Exception as e:
            logger.exception("get_container_ports: %s", e)
            return {}

    def load_single_container(self, worker_ip: str, container_id: str) -> Container:
        api_url = f"{self.remote_api_scheme}://{worker_ip}:{self.remote_api_port}" f"/containers/{container_id}/json"
        response = requests.get(api_url, timeout=self.remote_api_timeout, **self._remote_api_requests_kwargs())
        response.raise_for_status()
        container_data = response.json()
        return Container.from_id(container_data, worker_ip)
