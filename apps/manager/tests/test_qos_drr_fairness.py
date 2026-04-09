from __future__ import annotations

from classes.job.info.data.queuejob import QueueJob
from classes.job.jobthread import JobThread
from utils.metrics import QOS_DEFICIT_SPENT_TOTAL


class _InlineExecutor:
    """
    Deterministic executor used for scheduler tests:
    - available slots are fixed per call
    - submit executes inline (no threads)
    """

    def __init__(self, slots: int) -> None:
        self._slots = int(slots)
        self.submitted = 0

    def get_available_slots(self) -> int:
        return self._slots

    def submit(self, fn, msg) -> None:
        self.submitted += 1
        fn(msg)


def _spent(tenant_id: str, job_type: str) -> float:
    sample = QOS_DEFICIT_SPENT_TOTAL.collect()[0]
    for s in sample.samples:
        if s.labels.get("tenant_id") == tenant_id and s.labels.get("job_type") == job_type:
            return float(s.value)
    return 0.0


def test_drr_light_tenant_maintains_throughput_while_heavy_is_throttled() -> None:
    """
    Proof-of-excellence DRR test:

    - Two tenants enqueue the same job_type ("inference").
    - DRR quantum is configured so "heavy" cannot afford the cost per cycle.
    - "light" can afford exactly 1 dispatch per cycle.
    - We assert that light spends cost units deterministically while heavy spends 0.
    """

    jt = JobThread(
        max_workers_info=1,
        max_workers_management=1,
        max_workers_inference=1,
        max_executor_queue_info=10,
        max_executor_queue_management=10,
        max_executor_queue_inference=10,
        queue_cleanup_interval=9999,
        queue_idle_threshold=9999,
        max_queue_size_info_per_user=100,
        max_queue_size_management_per_user=100,
        max_queue_size_inference_per_user=100,
        qos={
            # DRR: base quantum is small; job cost is high.
            "base_quantum": 2,
            "job_type_costs": {"inference": 10, "management": 5, "info": 1},
            # Use legacy weights as multipliers (as implemented):
            # light gets 5x quantum, heavy gets 1x => light quantum=10, heavy quantum=2
            "job_type_weights": {"inference": 1, "management": 1, "info": 1},
            "tenant_weights": {"light": 5, "heavy": 1},
            "tenant_quantum_multipliers": {},
        },
    )

    # Two user queues, one per tenant (tenant_id is read from msg["_auth"]["tenant_id"]).
    q_heavy = QueueJob(maxsize=0)
    q_light = QueueJob(maxsize=0)

    for _ in range(200):
        q_heavy.put_nowait(
            {"uuid": "u-heavy", "type": "inference", "payload": {}, "_auth": {"tenant_id": "heavy"}}
        )
        q_light.put_nowait(
            {"uuid": "u-light", "type": "inference", "payload": {}, "_auth": {"tenant_id": "light"}}
        )

    queues = {"u-heavy": q_heavy, "u-light": q_light}
    exec_inline = _InlineExecutor(slots=1)

    before_light = _spent("light", "inference")
    before_heavy = _spent("heavy", "inference")

    # Run multiple scheduler cycles. With slots=1, the expected steady-state is:
    # - heavy cannot pay (deficit stays < cost) => 0 dispatches
    # - light can pay => 1 dispatch per cycle => spends 10 cost units per cycle
    cycles = 20
    for _ in range(cycles):
        jt.fair_process_queues(queues, exec_inline, handler=lambda m: None, job_type="inference")

    after_light = _spent("light", "inference")
    after_heavy = _spent("heavy", "inference")

    assert after_light == before_light + (cycles * 10)
    assert after_heavy == before_heavy

