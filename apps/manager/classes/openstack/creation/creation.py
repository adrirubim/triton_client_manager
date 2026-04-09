import logging
import time
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from ..auth import OpenstackAuth

logger = logging.getLogger(__name__)


###################################
#      VM Creation Handler        #
###################################


class OpenstackCreation:
    """Handles VM creation operations"""

    def __init__(self, auth: "OpenstackAuth", timeout: int, endpoint: str):
        self.auth = auth
        self.timeout = timeout
        self.endpoint = endpoint

    @property
    def headers_get(self):
        """Get headers with authentication token"""
        return {"Accept": "application/json", "X-Auth-Token": self.auth.token}

    @property
    def headers_post(self):
        """Get headers with authentication token"""
        return {
            "Accept": "application/json",
            "X-Auth-Token": self.auth.token,
            "Content-Type": "application/json",
            "OpenStack-API-Version": "compute 2.53",
        }

    def handle(
        self,
        name: str,
        keypair: str,
        image_id: str,
        security: str,
        flavor_id: str,
        network_id: str,
        config_drive: bool,
    ) -> tuple:
        # --- Data ---
        full_endpoint = self.auth.catalog.compute.endpoint_internal + self.endpoint
        payload = {
            "server": {
                "name": name,
                "key_name": keypair,
                "imageRef": image_id,
                "networks": [{"uuid": network_id}],
                "flavorRef": flavor_id,
                "config_drive": config_drive,
                "security_groups": [{"name": security}],
            }
        }

        # --- Send request ---
        response = requests.post(
            url=full_endpoint,
            json=payload,
            verify=self.auth.verify_ssl,
            timeout=10,
            headers=self.headers_post,
        )
        # --- Parse ---
        response.raise_for_status()
        vm_id = response.json()["server"]["id"]

        # --- Wait for Active ---
        vm_ip = self.loop_status(vm_id)
        return vm_ip, vm_id

    def loop_status(self, vm_id: str) -> str:
        # --- Endpoint ---
        full_endpoint = self.auth.catalog.compute.endpoint_internal + self.endpoint + "/" + vm_id
        # --- Timer ---
        start_time = time.time()
        vm_ip = None

        while (time.time() - start_time) < self.timeout:
            try:
                # --- Send request ---
                response = requests.get(
                    url=full_endpoint,
                    verify=self.auth.verify_ssl,
                    timeout=10,
                    headers=self.headers_get,
                )
                # --- Parse ---
                data: dict = response.json()["server"]
                vm_ip = self._extract_primary_ipv4(data.get("addresses", {}))
                vm_status = data.get("status", "")

                # --- I want to break free ---
                if vm_status == "ERROR":
                    raise Exception("VM Creation status in ->> ERROR <<-")
                if vm_status == "ACTIVE":
                    break

                time.sleep(3)

            except Exception as e:
                logger.exception("loop_status error: %s", e)
                return None

        else:
            logger.warning("Timeout waiting for VM %s to become ACTIVE", vm_id)
            return None

        return vm_ip

    @staticmethod
    def _extract_primary_ipv4(addresses: dict) -> str | None:
        """
        Nova returns IPs under server.addresses:
        {
          "<network_name>": [{"addr": "10.0.0.5", "version": 4, "OS-EXT-IPS:type": "fixed"}, ...],
          ...
        }
        Prefer IPv4 floating, then IPv4 fixed, else first IPv4 found.
        """
        if not isinstance(addresses, dict):
            return None

        ipv4_floating = None
        ipv4_fixed = None
        ipv4_any = None

        for _, iface_list in addresses.items():
            if not isinstance(iface_list, list):
                continue
            for iface in iface_list:
                if not isinstance(iface, dict):
                    continue
                if iface.get("version") != 4:
                    continue
                addr = iface.get("addr")
                if not addr:
                    continue
                ip_type = iface.get("OS-EXT-IPS:type")
                if ip_type == "floating" and not ipv4_floating:
                    ipv4_floating = addr
                elif ip_type == "fixed" and not ipv4_fixed:
                    ipv4_fixed = addr
                elif not ipv4_any:
                    ipv4_any = addr

        return ipv4_floating or ipv4_fixed or ipv4_any
