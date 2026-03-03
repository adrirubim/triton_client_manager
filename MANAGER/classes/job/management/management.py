from typing import TYPE_CHECKING, Callable

from classes.docker.dockererrors import DockerAPIError, DockerCreationMissingField, DockerImageNotFound
from classes.job.joberrors import (
    JobActionNotFound,
    JobContainerCreationFailed,
    JobDeletionFailed,
    JobDeletionMissingField,
    JobVMCreationFailed,
)
from classes.openstack.openstackerrors import OpenstackCreationMissingKey, OpenstackResourceNotFound
from classes.triton.tritonerrors import (
    TritonConfigDownloadFailed,
    TritonModelLoadFailed,
    TritonModelNotReady,
    TritonServerHealthFailed,
)

from .creation import JobCreation
from .deletion import JobDeletion

if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.openstack import OpenstackThread
    from classes.triton import TritonThread


###################################
#     Job Management Handler      #
###################################
class JobManagement:
    """Handles management-type job requests"""
    def __init__(self,
                 docker: "DockerThread",
                 triton: "TritonThread",
                 openstack: "OpenstackThread",
                 websocket: Callable[[str, dict], bool],
                 management_actions_available: list,
                 **kwargs):

        self.websocket = websocket
        self.management_actions_available = management_actions_available

        # Full pipelines
        self.job_creation = JobCreation(triton, docker, openstack)
        self.job_deletion = JobDeletion(triton, docker, openstack)

        # Individual steps — reuse sub-handlers from the pipelines
        self._vm_creator        = self.job_creation._vm
        self._vm_deleter        = self.job_deletion._vm
        self._container_creator = self.job_creation._container
        self._container_deleter = self.job_deletion._container
        self._server_creator    = self.job_creation._triton
        self._server_deleter    = self.job_deletion._triton

    def handle_management(self, msg: dict):
        """Process management request and send response"""

        try:
            msg_uuid: str = msg.get("uuid")
            msg_payload: dict = msg.get("payload", {})
            payload_action: str = msg_payload.get("action")

            if payload_action not in self.management_actions_available:
                raise JobActionNotFound(payload_action)

            action_function = getattr(self, payload_action, None)
            if not action_function:
                raise JobActionNotFound(payload_action)

            data = action_function(msg_uuid, msg_payload)
            status = True

        except JobActionNotFound as e:
            status = False
            data = str(e)
        except JobVMCreationFailed as e:
            status = False
            data = str(e)
        except JobContainerCreationFailed as e:
            status = False
            data = str(e)
        except JobDeletionMissingField as e:
            status = False
            data = str(e)
        except JobDeletionFailed as e:
            status = False
            data = str(e)
        except OpenstackCreationMissingKey as e:
            status = False
            data = str(e)
        except OpenstackResourceNotFound as e:
            status = False
            data = str(e)
        except DockerCreationMissingField as e:
            status = False
            data = str(e)
        except DockerImageNotFound as e:
            status = False
            data = str(e)
        except DockerAPIError as e:
            status = False
            data = str(e)
        except TritonServerHealthFailed as e:
            status = False
            data = str(e)
        except TritonModelLoadFailed as e:
            status = False
            data = str(e)
        except TritonModelNotReady as e:
            status = False
            data = str(e)
        except TritonConfigDownloadFailed as e:
            status = False
            data = str(e)
        except Exception as e:
            status = False
            data = f"Unexpected error: {str(e)}"
        finally:
            response_payload = msg.copy()
            response_payload["payload"] = {"status": status, "data": data}
            self.websocket(msg_uuid, response_payload)

    # Full pipelines
    def creation(self, msg_uuid: str, payload: dict):         return self.job_creation.handle(msg_uuid, payload)
    def deletion(self, msg_uuid: str, payload: dict):         return self.job_deletion.handle(msg_uuid, payload)

    # Individual creation steps
    def create_vm(self, msg_uuid: str, payload: dict):        return self._vm_creator.handle(msg_uuid, payload)
    def create_container(self, msg_uuid: str, payload: dict): return self._container_creator.handle(msg_uuid, payload)
    def create_server(self, msg_uuid: str, payload: dict):    return self._server_creator.handle(msg_uuid, payload)

    # Individual deletion steps
    def delete_server(self, msg_uuid: str, payload: dict):    return self._server_deleter.handle(msg_uuid, payload)
    def delete_container(self, msg_uuid: str, payload: dict): return self._container_deleter.handle(msg_uuid, payload)
    def delete_vm(self, msg_uuid: str, payload: dict):        return self._vm_deleter.handle(msg_uuid, payload)
