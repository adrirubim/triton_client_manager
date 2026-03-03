from unittest.mock import MagicMock

from classes.job.info.info import JobInfo


def test_job_info_queue_stats_happy_path():
    docker = MagicMock()
    openstack = MagicMock()

    def get_queue_stats():
        return {"info": {"pending": 1}}

    sent = []

    def ws(client_id, msg):
        sent.append((client_id, msg))
        return True

    ji = JobInfo(docker, openstack, ws, get_queue_stats)

    msg = {
        "uuid": "u1",
        "type": "info",
        "payload": {"action": "queue_stats", "job_id": "j1"},
    }
    ji.handle_info(msg)

    assert sent
    cid, payload = sent[0]
    assert cid == "u1"
    assert payload["type"] == "info_response"
    assert payload["payload"]["status"] == "success"
    assert payload["payload"]["data"] == {"info": {"pending": 1}}


def test_job_info_unknown_action_and_missing_websocket():
    docker = MagicMock()
    openstack = MagicMock()

    ji = JobInfo(docker, openstack, None, lambda: {})

    # Sin websocket, solo debe hacer print (no explota)
    msg = {
        "uuid": "u2",
        "type": "info",
        "payload": {"action": "other", "job_id": "j2"},
    }
    ji.handle_info(msg)


def test_job_info_error_flow_sends_error_response():
    docker = MagicMock()
    openstack = MagicMock()

    def bad_stats():
        raise RuntimeError("boom")

    sent = []

    def ws(client_id, msg):
        sent.append((client_id, msg))
        return True

    ji = JobInfo(docker, openstack, ws, bad_stats)

    msg = {
        "uuid": "u3",
        "type": "info",
        "payload": {"action": "queue_stats", "job_id": "j3"},
    }
    ji.handle_info(msg)

    assert sent
    cid, payload = sent[0]
    assert cid == "u3"
    assert payload["type"] == "info_response"
    assert payload["payload"]["status"] == "error"
    assert "boom" in payload["payload"]["error"]
