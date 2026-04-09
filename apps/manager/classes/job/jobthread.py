import logging
import threading
import time
from queue import Empty

# Import bounded executor instead of standard ThreadPoolExecutor
from utils.bounded_executor import BoundedThreadPoolExecutor
from utils.log_safety import safe_log_id
from utils.metrics import (
    observe_job_processing,
    observe_job_rejected,
    observe_qos_deficit_spent,
    observe_qos_slot_consumed,
)

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
        self.qos = (kwargs.get("qos") or {}) if isinstance(kwargs.get("qos"), dict) else {}
        self._job_type_weights = {}
        self._tenant_weights = {}
        self._job_type_costs = {"inference": 10, "management": 5, "info": 1}
        self._tenant_quantum_multipliers = {}
        self._base_quantum = 10
        self._deficit_counters: dict[str, dict[str, int]] = {"info": {}, "management": {}, "inference": {}}
        self._rr_cursor: dict[str, int] = {"info": 0, "management": 0, "inference": 0}
        self._last_budget_warn: dict[tuple[str, str], float] = {}
        try:
            jt = self.qos.get("job_type_weights") or {}
            tw = self.qos.get("tenant_weights") or {}
            costs = self.qos.get("job_type_costs") or {}
            tqm = self.qos.get("tenant_quantum_multipliers") or {}
            bq = self.qos.get("base_quantum", 10)
            if isinstance(jt, dict):
                self._job_type_weights = {str(k): int(v) for k, v in jt.items()}
            if isinstance(tw, dict):
                self._tenant_weights = {str(k): int(v) for k, v in tw.items()}
            if isinstance(costs, dict):
                self._job_type_costs = {str(k): int(v) for k, v in costs.items()}
            if isinstance(tqm, dict):
                self._tenant_quantum_multipliers = {str(k): int(v) for k, v in tqm.items()}
            self._base_quantum = int(bq)
        except Exception:
            # Keep defaults empty; scheduler will fall back to 1.
            self._job_type_weights = {}
            self._tenant_weights = {}

    def _weight_for(self, *, tenant_id: str, job_type: str) -> int:
        base = int(self._job_type_weights.get(job_type, 1))
        mult = int(self._tenant_weights.get(str(tenant_id or ""), 1))
        w = base * mult
        return w if w > 0 else 1

    def _cost_for(self, job_type: str) -> int:
        c = int(self._job_type_costs.get(job_type, 1))
        return c if c > 0 else 1

    def _quantum_for(self, *, tenant_id: str, job_type: str) -> int:
        """
        DRR quantum (cost units) granted to a tenant per scheduler cycle.

        We reuse the existing job_type_weights and tenant_weights as an extra
        multiplier to preserve Phase 9 semantics while moving to DRR.
        """
        base = int(self._base_quantum or 10)
        mult = int(self._tenant_quantum_multipliers.get(str(tenant_id or ""), 1))
        weight = self._weight_for(tenant_id=tenant_id, job_type=job_type)
        q = base * max(1, mult) * max(1, weight)
        return q if q > 0 else base

    def _peek_tenant_id(self, q: QueueJob) -> str:
        """
        Best-effort tenant_id peek without dequeuing.

        We rely on queue.Queue internals safely under q.mutex. If unavailable,
        we fall back to "unknown".
        """
        try:
            with q.mutex:  # type: ignore[attr-defined]
                if not q.queue:  # type: ignore[attr-defined]
                    return "unknown"
                msg = q.queue[0]  # type: ignore[attr-defined]
        except Exception:
            return "unknown"
        if not isinstance(msg, dict):
            return "unknown"
        auth = msg.get("_auth") or {}
        tid = auth.get("tenant_id")
        return str(tid) if isinstance(tid, str) and tid.strip() else "unknown"

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
                    self.inference_queues,
                    self.executor_inference,
                    self.job_inference.handle_inference,
                    "inference",
                )

                # --- Management ---
                self.fair_process_queues(
                    self.management_queues,
                    self.executor_management,
                    self.job_management.handle_management,
                    "management",
                )

                # --- Info ---
                self.fair_process_queues(
                    self.info_queues,
                    self.executor_info,
                    self.job_info.handle_info,
                    "info",
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

        Correlation / tracing:
        - WebSocketThread injects a per-message `_correlation_id` (UUID4 string).
        - For logging, we hash it via `safe_log_id(...)` and store it in the
          structured `correlation_id` field (never log the raw value).
        - There is no separate `request_id` concept in the manager at this time.
        """
        msg_uuid = msg.get("uuid")
        msg_type = msg.get("type")
        correlation_id = safe_log_id(msg.get("_correlation_id"))

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
        slots = int(executor.get_available_slots() or 0)
        if slots <= 0:
            return

        # --- Snapshot queues ---
        with self.queue_lock:
            user_ids = list(queue_dict.keys())

        # Build tenant -> [user_id...] for users with non-empty queues
        tenant_users: dict[str, list[str]] = {}
        for uid in user_ids:
            q = queue_dict.get(uid)
            if q is None or q.empty():
                continue
            tid = self._peek_tenant_id(q)
            tenant_users.setdefault(tid, []).append(uid)

        if not tenant_users:
            return

        tenants = list(tenant_users.keys())
        if job_type not in self._deficit_counters:
            self._deficit_counters[job_type] = {}
        deficit = self._deficit_counters[job_type]

        # DRR/TBF hybrid: grant quantum once per cycle (per call) but cap the
        # carry-over to avoid "saving up" budget indefinitely.
        #
        # This keeps the scheduler deterministic for unit tests where a tenant
        # with quantum < cost must remain throttled across cycles.
        for tid in tenants:
            q = int(self._quantum_for(tenant_id=tid, job_type=job_type))
            deficit[tid] = min(int(deficit.get(tid, 0)) + q, q)

        cost = self._cost_for(job_type)
        dispatched = 0

        cursor = int(self._rr_cursor.get(job_type, 0))
        scanned_without_progress = 0

        while dispatched < slots and tenants:
            if executor.get_available_slots() == 0:
                break

            tid = tenants[cursor % len(tenants)]
            cursor += 1

            # Not enough deficit → skip, but consider warning if queues are building.
            if int(deficit.get(tid, 0)) < int(cost):
                scanned_without_progress += 1
                # If everyone is below cost, break to avoid busy spin.
                if scanned_without_progress >= len(tenants):
                    # Best-effort semantic backpressure warning (not a drop).
                    self._maybe_warn_insufficient_budget(tenant_id=tid, job_type=job_type, tenant_users=tenant_users)
                    break
                continue

            users = tenant_users.get(tid) or []
            if not users:
                continue

            # Round-robin within tenant
            uid = users.pop(0)
            users.append(uid)
            tenant_users[tid] = users

            q = queue_dict.get(uid)
            if q is None:
                continue

            try:
                msg = q.get_nowait()
            except Empty:
                scanned_without_progress += 1
                # If we can't dequeue anything across a full tenant scan,
                # stop to avoid busy spinning on empty/stale snapshots.
                if scanned_without_progress >= len(tenants):
                    break
                continue
            except (OSError, ValueError, TypeError):
                continue

            deficit[tid] = int(deficit.get(tid, 0)) - int(cost)
            observe_qos_slot_consumed(tid, job_type)
            observe_qos_deficit_spent(tid, job_type, cost)

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
                            "correlation_id": safe_log_id(m.get("_correlation_id")),
                        },
                    )
                finally:
                    duration = time.time() - start
                    observe_job_processing(_job_type, duration)

            executor.submit(_wrapped, msg)
            dispatched += 1
            scanned_without_progress = 0

        self._rr_cursor[job_type] = cursor % max(1, len(tenants))

    def _maybe_warn_insufficient_budget(
        self,
        *,
        tenant_id: str,
        job_type: str,
        tenant_users: dict[str, list[str]],
    ) -> None:
        """
        Semantic backpressure: warn that a tenant is being throttled by DRR budget.
        This is a best-effort signal and rate-limited to avoid spamming clients.
        """
        now = time.time()
        key = (tenant_id, job_type)
        last = float(self._last_budget_warn.get(key, 0.0))
        if now - last < 5.0:
            return
        self._last_budget_warn[key] = now

        # Pick one user_id (uuid) from this tenant to notify.
        users = tenant_users.get(tenant_id) or []
        if not users:
            return
        msg_uuid = users[0]
        if not self.websocket:
            return
        try:
            self.websocket(
                msg_uuid,
                {
                    "type": "error",
                    "payload": {
                        "code": "BACKPRESSURE_INSUFFICIENT_BUDGET",
                        "message": "Request delayed due to tenant budget (DRR cost-aware fairness).",
                        "job_type": job_type,
                        "tenant_id": tenant_id,
                    },
                },
            )
        except Exception:
            # Best-effort only.
            return

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
