from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.triton import TritonThread


class JobCreateServer:
    def __init__(self, triton: "TritonThread"):
        self.triton = triton

    def handle(
        self, msg_uuid: str, payload: dict, vm_id=None, vm_ip=None, container_id=None
    ) -> dict:
        print(f"[Creation-{msg_uuid}] Step 3: Creating Triton server...")

        # --- Create payload ---
        data = {
            "vm_id": vm_id if vm_id else payload.get("openstack", {}).get("vm_id"),
            "vm_ip": vm_ip if vm_ip else payload.get("openstack", {}).get("vm_ip"),
            "minio": payload.get("minio", {}),
            "triton": payload.get("triton", {}),
            "container_id": (
                container_id
                if container_id
                else payload.get("docker", {}).get("container_id")
            ),
        }

        # --- Create server ---
        server = self.triton.create_server(data)

        print(
            f"[Creation-{msg_uuid}] ✓ Triton server ready — model='{server.model_name}'"
        )
        return {
            "model_name": server.model_name,
            "inputs": server.inputs,
            "outputs": server.outputs,
        }
