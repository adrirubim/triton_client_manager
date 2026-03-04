from __future__ import annotations

import time
from queue import Full

from classes.job.info.data.queuejob import QueueJob
from classes.job.jobthread import JobThread
from utils.metrics import JOB_PROCESSING_SECONDS, JOBS_REJECTED_TOTAL


def _make_jobthread():
    jt = JobThread(
        max_workers_info=1,
        max_workers_management=1,
        max_workers_inference=1,
        max_executor_queue_info=10,
        max_executor_queue_management=10,
        max_executor_queue_inference=10,
        queue_cleanup_interval=0,  # cleanup runs on first call
        queue_idle_threshold=0,
        max_queue_size_info_per_user=1,
        max_queue_size_management_per_user=1,
        max_queue_size_inference_per_user=1,
    )
    # Avoid spinning real threads / executors: patch fair_process_queues usage only.
    return jt


def _get_rejected_count(job_type: str) -> float:
    sample = JOBS_REJECTED_TOTAL.collect()[0]
    for s in sample.samples:
        if s.labels.get("type") == job_type:
            return float(s.value)
    return 0.0


def _get_processing_count(job_type: str) -> float:
    sample = JOB_PROCESSING_SECONDS.collect()[0]
    for s in sample.samples:
        if s.name.endswith("_count") and s.labels.get("type") == job_type:
            return float(s.value)
    return 0.0


def test_jobthread_on_message_creates_queues_and_routes_by_type(caplog):
    jt = _make_jobthread()

    # Use small custom QueueJob so we can inspect items
    jt.info_queues = {}
    jt.management_queues = {}
    jt.inference_queues = {}

    # Attach auth context to messages so role-based checks pass
    auth_all = {"_auth": {"roles": ["inference", "management"]}}

    msg_info = {"uuid": "u-info", "type": "info", "payload": {}, **auth_all}
    msg_mgmt = {"uuid": "u-mgmt", "type": "management", "payload": {}, **auth_all}
    msg_inf = {"uuid": "u-inf", "type": "inference", "payload": {}, **auth_all}
    msg_unknown = {"uuid": "u-x", "type": "unknown", "payload": {}}

    jt.on_message("u-info", msg_info)
    jt.on_message("u-mgmt", msg_mgmt)
    jt.on_message("u-inf", msg_inf)
    jt.on_message("u-x", msg_unknown)

    assert "u-info" in jt.info_queues
    assert "u-mgmt" in jt.management_queues
    assert "u-inf" in jt.inference_queues
    # Unknown type should not create a queue
    assert "u-x" not in jt.info_queues
    assert any("Unknown message type" in rec.message for rec in caplog.records)


def test_jobthread_on_message_logs_and_counts_when_queue_is_full(caplog, monkeypatch):
    jt = _make_jobthread()
    q = QueueJob(maxsize=1)
    q.put_nowait({"uuid": "u1", "type": "info", "payload": {}})
    jt.info_queues = {"u1": q}

    def boom(*args, **kwargs):
        raise Full()

    monkeypatch.setattr(q, "put_nowait", boom)

    before = _get_rejected_count("info")
    jt.on_message("u1", {"uuid": "u1", "type": "info", "payload": {}})
    after = _get_rejected_count("info")

    assert any("Queue full for user" in rec.message for rec in caplog.records)
    assert after == before + 1


def test_jobthread_cleanup_empty_queues_removes_idle_entries(caplog):
    jt = _make_jobthread()

    now = time.time()
    old = now - 10

    # Create idle, empty queues with old last_entry timestamps
    qi = QueueJob(maxsize=1)
    qi.last_entry = old
    qm = QueueJob(maxsize=1)
    qm.last_entry = old
    qf = QueueJob(maxsize=1)
    qf.last_entry = old

    jt.info_queues = {"u-info": qi}
    jt.management_queues = {"u-mgmt": qm}
    jt.inference_queues = {"u-inf": qf}
    jt.last_cleanup_time = now - 10  # force cleanup

    jt.cleanup_empty_queues()

    assert jt.info_queues == {}
    assert jt.management_queues == {}
    assert jt.inference_queues == {}


def test_jobthread_fair_process_queues_records_processing_time(monkeypatch):
    jt = _make_jobthread()

    # Prepare a queue with a single info job
    q = QueueJob(maxsize=1)
    q.put_nowait({"uuid": "u1", "type": "info", "payload": {}})
    jt.info_queues = {"u1": q}

    def fake_handler(_msg):
        # Simulate small processing time
        time.sleep(0.001)

    before = _get_processing_count("info")
    jt.fair_process_queues(jt.info_queues, jt.executor_info, fake_handler, "info")
    # Give the executor a moment to run the job
    time.sleep(0.01)
    after = _get_processing_count("info")

    assert after >= before + 1
