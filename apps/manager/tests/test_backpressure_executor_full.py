import time

from classes.job.jobthread import JobThread
from utils.bounded_executor import ExecutorQueueFull


def _make_minimal_jobthread() -> JobThread:
    return JobThread(
        max_workers_info=1,
        max_workers_management=1,
        max_workers_inference=1,
        max_executor_queue_info=1,
        max_executor_queue_management=1,
        max_executor_queue_inference=1,
        queue_cleanup_interval=3600,
        queue_idle_threshold=3600,
        max_queue_size_info_per_user=10,
        max_queue_size_management_per_user=10,
        max_queue_size_inference_per_user=10,
    )


def test_executor_queue_full_sends_nack_and_does_not_block(monkeypatch) -> None:
    """
    When the bounded executor rejects a submit, JobThread must:
    - not block (liveness),
    - emit a backpressure NACK with code BACKPRESSURE_EXECUTOR_FULL.
    """
    jt = _make_minimal_jobthread()

    sent: list[tuple[str, dict]] = []

    def fake_ws(client_id: str, message: dict) -> bool:
        sent.append((client_id, message))
        return True

    jt.websocket = fake_ws

    # Force the executor submit to behave as "full" regardless of available slots.
    def reject_submit(_fn, *_args, **_kwargs):
        raise ExecutorQueueFull("full")

    monkeypatch.setattr(jt.executor_inference, "submit", reject_submit)
    monkeypatch.setattr(
        jt.executor_inference,
        "get_available_slots",
        lambda: 1,
    )

    # Seed a single queued inference message (already authorized).
    msg_uuid = "u1"
    q = jt.get_or_create_queue(
        user_id=msg_uuid,
        max_size=jt.max_queue_size_inference_per_user,
        queue_dict=jt.inference_queues,
    )
    q.put_nowait(
        {
            "uuid": msg_uuid,
            "type": "inference",
            "payload": {"model_name": "demo"},
            "_auth": {"tenant_id": "t1", "roles": ["inference"]},
            "_correlation_id": "corr",
        }
    )

    start = time.perf_counter()
    jt.fair_process_queues(
        jt.inference_queues,
        jt.executor_inference,
        handler=lambda _m: None,
        job_type="inference",
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.25, "Scheduler path should not block on executor saturation"
    assert sent, "Expected a backpressure NACK to be sent"
    client_id, msg = sent[-1]
    assert client_id == msg_uuid
    assert msg.get("type") == "error"
    payload = msg.get("payload") or {}
    assert payload.get("code") == "BACKPRESSURE_EXECUTOR_FULL"
    assert payload.get("dropped_type") == "inference"
