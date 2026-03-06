from typing import TYPE_CHECKING, Callable

# Only import for type checking, not at runtime
if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.openstack import OpenstackThread

###################################
#        Job Info Handler         #
###################################


class JobInfo:
    """Handles info-type job requests"""

    def __init__(
        self,
        docker: "DockerThread",
        openstack: "OpenstackThread",
        websocket: Callable[[str, dict], bool],
        get_queue_stats: Callable[[], dict],
    ):

        self.docker = docker
        self.openstack = openstack
        self.websocket = websocket  # Now expects (client_id, message)
        self.get_queue_stats = get_queue_stats

    def handle_info(self, msg: dict):
        """Process info request and send response"""
        try:
            msg_uuid = msg.get("uuid")
            payload = msg.get("payload", {})
            request_type = payload.get("action", payload.get("request_type", "unknown"))

            # Handle different info request types
            if request_type in ("queue", "queue_stats"):
                # Get queue statistics
                stats = self.get_queue_stats()
                data = stats
            else:
                # Example: Check container status, model availability, etc.
                data = {"message": f"Info type '{request_type}' not implemented yet"}

            result = {
                "type": "info_response",
                "payload": {
                    "job_id": payload.get("job_id"),
                    "request_type": request_type,
                    "status": "success",
                    "data": data,
                },
            }

            # Send response to specific client
            if self.websocket and msg_uuid:
                self.websocket(msg_uuid, result)
            else:
                print("[Error] JobInfo.handle_info: Missing uuid or websocket")

        except Exception as e:
            print(f"[Error] JobInfo.handle_info: {e}")

            # Try to send error response
            try:
                msg_uuid = msg.get("uuid")
                if self.websocket and msg_uuid:
                    error_result = {
                        "type": "info_response",
                        "payload": {
                            "job_id": payload.get("job_id"),
                            "status": "error",
                            "error": str(e),
                        },
                    }
                    self.websocket(msg_uuid, error_result)
            except Exception:
                pass
