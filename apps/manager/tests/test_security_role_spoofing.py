from __future__ import annotations

from classes.job.jobthread import JobThread


def _make_jobthread() -> JobThread:
    jt = JobThread(
        max_workers_info=1,
        max_workers_management=1,
        max_workers_inference=1,
        max_executor_queue_info=10,
        max_executor_queue_management=10,
        max_executor_queue_inference=10,
        queue_cleanup_interval=999,
        queue_idle_threshold=999,
        max_queue_size_info_per_user=10,
        max_queue_size_management_per_user=10,
        max_queue_size_inference_per_user=10,
    )
    jt.info_queues = {}
    jt.management_queues = {}
    jt.inference_queues = {}
    return jt


def test_jobthread_rejects_management_when_roles_missing_and_payload_spoofs_roles() -> None:
    jt = _make_jobthread()
    sent: list[tuple[str, dict]] = []

    def fake_ws(client_id: str, msg: dict) -> bool:
        sent.append((client_id, msg))
        return True

    jt.websocket = fake_ws

    # Client tries to "spoof" roles in payload; JobThread must ONLY trust msg["_auth"].
    msg = {
        "uuid": "u1",
        "type": "management",
        "payload": {"client": {"roles": ["admin", "management"]}},
        "_correlation_id": "corr-1",
    }
    jt.on_message("u1", msg)

    assert jt.management_queues == {}
    assert sent
    assert sent[-1][0] == "u1"
    assert sent[-1][1]["type"] == "error"
    assert "Forbidden" in sent[-1][1]["payload"]["message"]


def test_jobthread_rejects_inference_when_roles_missing_and_payload_spoofs_roles() -> None:
    jt = _make_jobthread()
    sent: list[tuple[str, dict]] = []

    def fake_ws(client_id: str, msg: dict) -> bool:
        sent.append((client_id, msg))
        return True

    jt.websocket = fake_ws

    msg = {
        "uuid": "u2",
        "type": "inference",
        "payload": {"client": {"roles": ["admin", "inference"]}},
        "_correlation_id": "corr-2",
    }
    jt.on_message("u2", msg)

    assert jt.inference_queues == {}
    assert sent
    assert sent[-1][0] == "u2"
    assert sent[-1][1]["type"] == "error"
    assert "Forbidden" in sent[-1][1]["payload"]["message"]


def test_jobthread_allows_management_when_roles_present_in_auth_context() -> None:
    jt = _make_jobthread()
    msg = {
        "uuid": "u3",
        "type": "management",
        "payload": {},
        "_auth": {"roles": ["management"]},
        "_correlation_id": "corr-3",
    }
    jt.on_message("u3", msg)
    assert "u3" in jt.management_queues


def test_jobthread_allows_inference_when_roles_present_in_auth_context() -> None:
    jt = _make_jobthread()
    msg = {
        "uuid": "u4",
        "type": "inference",
        "payload": {},
        "_auth": {"roles": ["inference"]},
        "_correlation_id": "corr-4",
    }
    jt.on_message("u4", msg)
    assert "u4" in jt.inference_queues
