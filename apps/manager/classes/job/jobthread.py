import logging
import threading
import time
from queue import Empty

# Import bounded executor instead of standard ThreadPoolExecutor
from utils.bounded_executor import BoundedThreadPoolExecutor
from utils.metrics import observe_job_processing, observe_job_rejected

from .inference import JobInference

# Import job handlers from their respective modules
from .info import JobInfo

# Import custom QueueJob class
from .info.data.queuejob import QueueJob
from .management import JobManagement

logger = logging.getLogger(__name__)


###################################
#          Job Thread             #
###################################


class JobThread(threading.Thread):
    """
    Manages job processing with per-user fair queuing.

    - Info jobs: Per-user queues (fair scheduling)          -> Information regarding PIPELINES ( Openstack + Docker )
    - Management jobs: Per-user queues (fair scheduling)    -> Management of Vms + Docker + PIPELINES
    - Inference jobs: Per-user queues (fair scheduling)     -> Inference request to PIPELINES
    """

    def __init__(
        self,
        max_workers_info: int,
        max_workers_management: int,
        max_workers_inference: int,
        max_executor_queue_info: int,
        max_executor_queue_management: int,
        max_executor_queue_inference: int,
        queue_cleanup_interval: int,
        queue_idle_threshold: int,
        max_queue_size_info_per_user: int,
        max_queue_size_management_per_user: int,
        max_queue_size_inference_per_user: int,
        **kwargs,
    ):
        super().__init__(name="Job_Thread", daemon=True)
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()

        # Queue configuration
        self.queue_cleanup_interval = queue_cleanup_interval
        self.queue_idle_threshold = queue_idle_threshold
        self.max_queue_size_info_per_user = max_queue_size_info_per_user
        self.max_queue_size_management_per_user = max_queue_size_management_per_user
        self.max_queue_size_inference_per_user = max_queue_size_inference_per_user

        # Queues - all per-user now
        self.queue_lock = threading.Lock()
        self.info_queues: dict[str, QueueJob] = {}  # {user_id: QueueJob}
        self.management_queues: dict[str, QueueJob] = {}  # {user_id: QueueJob}
        self.inference_queues: dict[str, QueueJob] = {}  # {user_id: QueueJob}

        # Bounded Executors - prevent unbounded queue growth
        self.executor_info = BoundedThreadPoolExecutor(
            max_workers=max_workers_info,
            max_queue_size=max_executor_queue_info,
            thread_name_prefix="Info-Worker-",
        )

        self.executor_management = BoundedThreadPoolExecutor(
            max_workers=max_workers_management,
            max_queue_size=max_executor_queue_management,
            thread_name_prefix="Management-Worker-",
        )

        self.executor_inference = BoundedThreadPoolExecutor(
            max_workers=max_workers_inference,
            max_queue_size=max_executor_queue_inference,
            thread_name_prefix="Inference-Worker-",
        )
        # Dependencies (set by ClientManager)
        self.docker = None
        self.openstack = None
        self.websocket = None
        self.triton = None

        # Job handlers (initialized in start())
        self.job_info = None
        self.job_management = None
        self.job_inference = None

        # Cleanup tracking
        self.last_cleanup_time = time.time()

        # Extra
        self.kwargs = kwargs

    # --------------- Thread Related ---------------
    def start(self):
        """Initialize job handlers with dependencies before starting thread"""

        self.job_info = JobInfo(
            self.docker,
            self.openstack,
            self.websocket,
            self.get_queue_stats,
        )
        self.job_management = JobManagement(
            self.docker,
            self.triton,
            self.openstack,
            self.websocket,
            self.kwargs.get("management_actions_available", []),
        )
        self.job_inference = JobInference(
            self.triton,
            self.docker,
            self.openstack,
            self.websocket,
        )

        self._ready_event.set()  # Signal that initialization is complete
        super().start()

    def wait_until_ready(self, timeout=30):
        """Wait for job handlers to be initialized"""
        return self._ready_event.wait(timeout)

    def run(self) -> None:
        logger.info(
            "Started",
            extra={"job_id": "-", "job_type": "job_loop"},
        )

        while not self._stop_event.is_set():
            try:
                # --- Info ---
                self.fair_process_queues(
                    self.info_queues,
                    self.executor_info,
                    self.job_info.handle_info,
                    "info",
                )

                # --- Management ---
                self.fair_process_queues(
                    self.management_queues,
                    self.executor_management,
                    self.job_management.handle_management,
                    "management",
                )

                # --- Inference ---
                self.fair_process_queues(
                    self.inference_queues,
                    self.executor_inference,
                    self.job_inference.handle_inference,
                    "inference",
                )

                # -- Clean-Up ---
                self.cleanup_empty_queues()

                # Small sleep to prevent busy-waiting
                time.sleep(0.01)

            except Exception as e:
                logger.exception(
                    "Main loop error: %s",
                    e,
                    extra={"job_id": "-", "job_type": "job_loop"},
                )

        logger.info(
            "Stopped",
            extra={"job_id": "-", "job_type": "job_loop"},
        )

    def stop(self) -> None:
        """Stop the thread and shutdown executors"""
        logger.info(
            "Stopping",
            extra={"job_id": "-", "job_type": "job_loop"},
        )
        self._stop_event.set()

        # Shutdown executors gracefully
        self.executor_info.shutdown(wait=True)
        self.executor_management.shutdown(wait=True)
        self.executor_inference.shutdown(wait=True)

    # --------------- Request Handler ---------------
    def on_message(self, client_id: str, msg: dict):
        """
        Route incoming message to appropriate queue.
        Called by WebSocketThread when message arrives.
        """
        msg_uuid = msg.get("uuid")
        msg_type = msg.get("type")
        correlation_id = msg.get("_correlation_id", "-")

        # Authorization context (populated by WebSocketThread if available)
        auth_ctx = msg.get("_auth", {})
        roles = auth_ctx.get("roles") or []

        # --- Queue Separation Logic ---
        try:
            if msg_type == "info":
                queue = self.get_or_create_queue(
                    user_id=msg_uuid,
                    max_size=self.max_queue_size_info_per_user,
                    queue_dict=self.info_queues,
                )
            elif msg_type == "management":
                # Simple role-based authorization: require "management" or "admin"
                if "management" not in roles and "admin" not in roles:
                    if self.websocket:
                        self.websocket(
                            msg_uuid,
                            {
                                "type": "error",
                                "payload": {"message": "Forbidden: missing 'management' role"},
                            },
                        )
                    logger.warning(
                        "Rejected management request due to missing role",
                        extra={
                            "job_id": "-",
                            "job_type": "authz_reject",
                            "correlation_id": correlation_id,
                        },
                    )
                    return
                queue = self.get_or_create_queue(
                    user_id=msg_uuid,
                    max_size=self.max_queue_size_management_per_user,
                    queue_dict=self.management_queues,
                )
            elif msg_type == "inference":
                # Simple role-based authorization: require "inference" or "admin"
                if "inference" not in roles and "admin" not in roles:
                    if self.websocket:
                        self.websocket(
                            msg_uuid,
                            {
                                "type": "error",
                                "payload": {"message": "Forbidden: missing 'inference' role"},
                            },
                        )
                    logger.warning(
                        "Rejected inference request due to missing role",
                        extra={
                            "job_id": "-",
                            "job_type": "authz_reject",
                            "correlation_id": correlation_id,
                        },
                    )
                    return
                queue = self.get_or_create_queue(
                    user_id=msg_uuid,
                    max_size=self.max_queue_size_inference_per_user,
                    queue_dict=self.inference_queues,
                )
            else:
                # Intentionally avoid logging user identifiers or raw message
                # contents here; we only record that an unexpected type reached
                # the dispatcher.
                logger.error("Unknown message type for incoming message")
                queue = None

            if queue:
                queue.put_nowait(msg)

        except Exception:
            # Queue full (or other queue-level error) -> backpressure metric
            if msg_type in {"info", "management", "inference"}:
                observe_job_rejected(msg_type)

            # Avoid logging user identifiers or raw exception messages; the
            # corresponding Prometheus metric already captures the rejection.
            logger.warning("Queue full for incoming message (backpressure activated)")

            # Explicit backpressure NACK to client (no payload echo).
            if self.websocket and msg_uuid and msg_type in {"info", "management", "inference"}:
                try:
                    self.websocket(
                        msg_uuid,
                        {
                            "type": "error",
                            "payload": {
                                "code": "BACKPRESSURE_QUEUE_FULL",
                                "message": "Request dropped due to backpressure (per-user queue full).",
                                "dropped_type": msg_type,
                            },
                        },
                    )
                except Exception:
                    # Best-effort only; never recurse into logging sensitive context.
                    logger.debug(
                        "Failed to send backpressure NACK to client",
                        extra={
                            "job_id": "-",
                            "job_type": "backpressure_nack_failed",
                        },
                    )

    # --------------- Queue Related ---------------
    def fair_process_queues(
        self,
        queue_dict: dict[str, QueueJob],
        executor: BoundedThreadPoolExecutor,
        handler,
        job_type: str,
    ):
        # --- Executor Status ---
        if executor.get_available_slots() == 0:
            return

        # --- Retrieve ---
        with self.queue_lock:
            user_ids = list(queue_dict.keys())

        for user_id in user_ids:
            try:
                # --- Executor Status ---
                if executor.get_available_slots() == 0:
                    continue

                # --- Get ---
                queue = queue_dict.get(user_id)
                if queue is None:
                    continue
                msg = queue.get_nowait()

                # --- Execute ---
                def _wrapped(m: dict, _handler=handler, _job_type=job_type) -> None:
                    start = time.time()
                    try:
                        _handler(m)
                    except Exception:
                        logger.exception(
                            "Job handler error",
                            extra={
                                "job_id": "-",
                                "job_type": _job_type,
                                "correlation_id": m.get("_correlation_id", "-"),
                            },
                        )
                    finally:
                        duration = time.time() - start
                        observe_job_processing(_job_type, duration)

                executor.submit(_wrapped, msg)

            except Empty:
                continue
            except Exception as e:
                logger.exception(
                    "Error processing per-user queue",
                    extra={
                        "job_id": "-",
                        "job_type": "queue_process",
                        "queue_error": str(e),
                    },
                )

    def cleanup_empty_queues(self):
        """
        Clean up empty queues that have been idle for longer than the threshold.
        Only removes queues that are both empty AND haven't received messages
        for queue_idle_threshold seconds.
        """
        # --- Timer ---
        current_time = time.time()
        if (current_time - self.last_cleanup_time) < self.queue_cleanup_interval:
            return

        # --- Info ---
        with self.queue_lock:
            empty_info = [
                uid
                for uid, q in self.info_queues.items()
                if q.empty() and (current_time - q.last_entry) > self.queue_idle_threshold
            ]
            for uid in empty_info:
                del self.info_queues[uid]

        # --- Management ---
        with self.queue_lock:
            empty_management = [
                uid
                for uid, q in self.management_queues.items()
                if q.empty() and (current_time - q.last_entry) > self.queue_idle_threshold
            ]
            for uid in empty_management:
                del self.management_queues[uid]

        # --- Inference ---
        with self.queue_lock:
            empty_inference = [
                uid
                for uid, q in self.inference_queues.items()
                if q.empty() and (current_time - q.last_entry) > self.queue_idle_threshold
            ]
            for uid in empty_inference:
                del self.inference_queues[uid]

        self.last_cleanup_time = current_time

        # --- Log ---
        if empty_info or empty_management or empty_inference:
            logger.info(
                "Cleaned up %d info, %d management and %d inference queues",
                len(empty_info),
                len(empty_management),
                len(empty_inference),
                extra={
                    "job_id": "-",
                    "job_type": "queue_cleanup",
                },
            )

    def get_or_create_queue(self, user_id: str, max_size: int, queue_dict: dict) -> QueueJob:
        """
        Thread-safe queue creation for per-user queues.
        Creates queue on-demand when user first sends request.
        """
        with self.queue_lock:
            if user_id not in queue_dict:
                queue_dict[user_id] = QueueJob(maxsize=max_size)
                # Do not log the concrete user identifier here; only that a
                # queue was created. More detailed per-user traces should be
                # added in upstream systems if required.
                logger.info(
                    "Created per-user queue",
                    extra={
                        "job_id": "-",
                        "job_type": "queue_create",
                    },
                )
            return queue_dict[user_id]

    # ------------ INFO ------------
    def get_queue_stats(self) -> dict:
        """Get statistics for monitoring"""
        with self.queue_lock:
            # Per-type counts
            info_users_count = len(self.info_queues)
            management_users_count = len(self.management_queues)
            inference_users_count = len(self.inference_queues)

            info_total_queued = sum(q.qsize() for q in self.info_queues.values())
            management_total_queued = sum(q.qsize() for q in self.management_queues.values())
            inference_total_queued = sum(q.qsize() for q in self.inference_queues.values())

            # Aggregate view across all types (unique users and total queued)
            total_unique_users = len(
                set(self.info_queues.keys()) | set(self.management_queues.keys()) | set(self.inference_queues.keys())
            )
            total_queued = info_total_queued + management_total_queued + inference_total_queued

            return {
                # Per-user queue stats
                "info_users": info_users_count,
                "management_users": management_users_count,
                "inference_users": inference_users_count,
                # Aggregate queue stats
                "total_users": total_unique_users,
                "total_queued": total_queued,
                "info_total_queued": info_total_queued,
                "management_total_queued": management_total_queued,
                "inference_total_queued": inference_total_queued,
                # Executor queue stats
                "executor_info_pending": self.executor_info.get_queue_size(),
                "executor_management_pending": self.executor_management.get_queue_size(),
                "executor_inference_pending": self.executor_inference.get_queue_size(),
                # Executor capacity
                "executor_info_available": self.executor_info.get_available_slots(),
                "executor_management_available": self.executor_management.get_available_slots(),
                "executor_inference_available": self.executor_inference.get_available_slots(),
            }
