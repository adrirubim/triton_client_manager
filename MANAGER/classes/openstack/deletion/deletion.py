import time
from typing import TYPE_CHECKING

import requests

from ..openstackerrors import (
    OpenstackDeletionError,
    OpenstackDeletionMissingVM,
    OpenstackDeletionTimeout,
)

if TYPE_CHECKING:
    from ..auth import OpenstackAuth


###################################
#      VM Deletion Handler        #
###################################


class OpenstackDeletion:
    """Handles VM deletion operations"""

    def __init__(self, auth: "OpenstackAuth", timeout: int, endpoint: str):

        self.auth = auth
        self.timeout = timeout
        self.endpoint = endpoint

    @property
    def headers_get(self):
        """Get headers with authentication token"""
        return {"Accept": "application/json", "X-Auth-Token": self.auth.token}

    def handle(self, vm_id: str):

        # --- Data ---
        full_endpoint = self.auth.catalog.compute.endpoint_internal
        full_endpoint += self.endpoint + "/" + vm_id

        try:
            # --- Send delete request ---
            response = requests.delete(
                url=full_endpoint,
                verify=self.auth.verify_ssl,
                timeout=10,
                headers=self.headers_get,
            )
            # --- Parse ---
            response.raise_for_status()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise OpenstackDeletionMissingVM(vm_id)
            else:
                raise OpenstackDeletionError(e, vm_id)

        except Exception as e:
            raise OpenstackDeletionError(e, vm_id)

        # --- Timer ---
        start_time = time.time()

        while (time.time() - start_time) < self.timeout:
            try:
                # --- Send request ---
                response = requests.get(
                    url=full_endpoint,
                    verify=self.auth.verify_ssl,
                    timeout=10,
                    headers=self.headers_get,
                )

                # --- 404 = SUCCESS (VM is deleted!) ---
                if response.status_code == 404:
                    return

                # --- Still exists, keep waiting ---
                time.sleep(3)

            except requests.exceptions.HTTPError as e:
                # --- 404 = SUCCESS ---
                if e.response.status_code == 404:
                    return
                raise OpenstackDeletionError(e, vm_id)

            except Exception as e:
                raise OpenstackDeletionError(e, vm_id)

        # --- Timeout ---
        raise OpenstackDeletionTimeout(vm_id)
