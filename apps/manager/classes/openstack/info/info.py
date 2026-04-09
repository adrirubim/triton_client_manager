from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..auth import OpenstackAuth

import requests

from .data import VM, Flavor, Host, Image, Keypair, Network, Security


class OpenstackInfo:
    """Handles OpenStack resource information loading via generic config-driven approach"""

    def __init__(self, auth: "OpenstackAuth", endpoints: dict):
        self.auth = auth
        self.endpoints = endpoints
        self.data_classes = {
            "VM": VM,
            "Host": Host,
            "Image": Image,
            "Flavor": Flavor,
            "Network": Network,
            "Keypair": Keypair,
            "Security": Security,
        }

    # --------------- UTILS ---------------
    @property
    def headers(self):
        """Get headers with authentication token"""
        return {
            "X-Auth-Token": self.auth.token,
            "OpenStack-API-Version": "compute 2.53",
        }

    def execute_request(self, endpoint: str) -> dict:
        """Execute GET request to OpenStack API"""
        response = requests.get(endpoint, headers=self.headers, verify=self.auth.verify_ssl, timeout=5)
        response.raise_for_status()
        return response.json()

    def _load(self, resource_type: str) -> dict:
        """Generic loader for any resource type from config"""
        config = self.endpoints[resource_type]
        service = getattr(self.auth.catalog, config["service"])
        endpoint = service.endpoint_internal + config["path"]
        data = self.execute_request(endpoint)
        data_class = self.data_classes[config["data_class"]]
        return data_class.from_api(data)

    # --------------- INFO ---------------
    def load_vms(self):
        return self._load("vms")

    def load_hosts(self):
        return self._load("hosts")

    def load_images(self):
        return self._load("images")

    def load_flavors(self):
        return self._load("flavors")

    def load_networks(self):
        return self._load("networks")

    def load_keypairs(self):
        return self._load("keypairs")

    def load_security(self):
        return self._load("security")

    # --------------- HELPERS ---------------
    def get_vm_id_by_ip(self, dict_vms: dict, vm_ip: str) -> str:
        for vm_id, vm in dict_vms.items():
            if vm.address_private == vm_ip:
                return vm_id
        return None

    def load_single_vm(self, vm_id: str) -> VM:
        config = self.endpoints["vms"]
        service = getattr(self.auth.catalog, config["service"])
        endpoint = service.endpoint_internal + config["path"].replace("/detail", f"/{vm_id}")
        data = self.execute_request(endpoint)
        return VM.from_id(data.get("server", {}))
