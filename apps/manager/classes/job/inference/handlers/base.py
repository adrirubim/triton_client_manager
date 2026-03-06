from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.docker import DockerThread


def check_instance(docker: "DockerThread", vm_ip: str, container_id: str) -> None:
    container = docker.dict_containers.get(container_id)
    if container is None:
        raise ValueError(
            f"Container '{container_id[:12]}' not found in known containers"
        )
    if container.worker_ip != vm_ip:
        raise ValueError(
            f"Container '{container_id[:12]}' is not on VM '{vm_ip}' (found on '{container.worker_ip}')"
        )


def validate_fields(payload: dict) -> tuple:
    """Returns (vm_ip, container_id, model_name, inputs). Raises ValueError if any missing."""
    vm_ip = payload.get("vm_ip")
    container_id = payload.get("container_id")
    model_name = payload.get("model_name")
    inputs = payload.get("request", {}).get("inputs", [])

    if not vm_ip:
        raise ValueError("Missing required field 'vm_ip'")
    if not container_id:
        raise ValueError("Missing required field 'container_id'")
    if not model_name:
        raise ValueError("Missing required field 'model_name'")
    if not inputs:
        raise ValueError("Missing required field 'request.inputs'")

    return vm_ip, container_id, model_name, inputs
