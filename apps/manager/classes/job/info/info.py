import logging
from typing import TYPE_CHECKING, Callable

# Only import for type checking, not at runtime
if TYPE_CHECKING:
    from classes.docker import DockerThread
    from classes.openstack import OpenstackThread

logger = logging.getLogger(__name__)

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
        msg_uuid = msg.get("uuid")
        payload = msg.get("payload", {}) or {}
        request_type = payload.get("action", payload.get("request_type", "unknown"))

        try:
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
                logger.error(
                    "JobInfo.handle_info: Missing uuid or websocket",
                    extra={
                        "client_uuid": msg_uuid or "-",
                        "job_id": payload.get("job_id") or "-",
                        "job_type": "info",
                    },
                )

        except Exception as e:  # noqa: BLE001
            logger.exception(
                "JobInfo.handle_info failed",
                extra={
                    "client_uuid": msg_uuid or "-",
                    "job_id": payload.get("job_id") or "-",
                    "job_type": "info",
                    "request_type": request_type,
                },
            )

            # Try to send error response
            try:
                if self.websocket and msg_uuid:
                    error_result = {
                        "type": "info_response",
                        "payload": {
                            "job_id": payload.get("job_id"),
                            "request_type": request_type,
                            "status": "error",
                            # Keep both a top-level `error` field (for older tests/consumers)
                            # and a structured `data.error` field for newer callers.
                            "error": str(e),
                            "data": {"error": str(e)},
                        },
                    }
                    self.websocket(msg_uuid, error_result)
            except Exception as send_err:
                logger.exception(
                    "JobInfo.handle_info: failed to send error response",
                    extra={
                        "client_uuid": msg_uuid or "-",
                        "job_id": payload.get("job_id") or "-",
                        "job_type": "info",
                        "request_type": request_type,
                        "send_error": str(send_err),
                    },
                )
