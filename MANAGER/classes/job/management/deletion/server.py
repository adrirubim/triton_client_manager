from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from classes.triton import TritonThread


class JobDeleteServer:
    def __init__(self, triton: "TritonThread"):
        self.triton = triton

    def handle(self, msg_uuid: str, payload: dict) -> dict:
        print(f"[Deletion-{msg_uuid}] Step 1: Deleting Triton server...")

        # --- Execute ---
        self.triton.delete_server(payload)

        print(f"[Deletion-{msg_uuid}] ✓ Triton server deregistered")
        return payload
