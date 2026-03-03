from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.docker import DockerThread


class JobDeleteContainer:
    def __init__(self, docker: "DockerThread"):
        self.docker = docker

    def handle(self, msg_uuid: str, payload: dict) -> str:
        print(f"[Deletion-{msg_uuid}] Step 2: Deleting Docker container...")

        # --- Execute ---
        self.docker.delete_container(payload)


        print(f"[Deletion-{msg_uuid}] ✓ Container deleted")
        return payload
