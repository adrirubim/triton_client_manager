from unittest.mock import MagicMock

import pytest

from classes.job.inference.inference import JobInference
from classes.job.joberrors import (
    JobInferenceMissingField,
)
from classes.job.management.management import JobManagement
from classes.triton import TritonInfer
from classes.triton.tritonerrors import TritonInferenceFailed


def _make_ws_collector():
    sent = []

    def _ws(uuid, payload):
        sent.append((uuid, payload))
        return True

    return sent, _ws


def test_job_management_handles_known_action_and_wraps_result():
    docker = MagicMock()
    triton = MagicMock()
    openstack = MagicMock()
    sent, ws = _make_ws_collector()

    jm = JobManagement(
        docker=docker,
        triton=triton,
        openstack=openstack,
        websocket=ws,
        management_actions_available=["creation"],
    )

    # Stub pipelines
    jm.job_creation = MagicMock()
    jm.job_creation.handle.return_value = {"ok": True}

    msg = {"uuid": "u1", "payload": {"action": "creation", "data": {"x": 1}}}
    jm.handle_management(msg)

    assert len(sent) == 1
    uuid, payload = sent[0]
    assert uuid == "u1"
    assert payload["payload"]["status"] is True
    assert payload["payload"]["data"] == {"ok": True}


def test_job_management_unknown_action_sets_status_false():
    docker = MagicMock()
    triton = MagicMock()
    openstack = MagicMock()
    sent, ws = _make_ws_collector()

    jm = JobManagement(
        docker=docker,
        triton=triton,
        openstack=openstack,
        websocket=ws,
        management_actions_available=["creation"],
    )

    msg = {"uuid": "u1", "payload": {"action": "nonexistent"}}
    jm.handle_management(msg)

    assert len(sent) == 1
    uuid, payload = sent[0]
    assert uuid == "u1"
    assert payload["payload"]["status"] is False
    # El mensaje proviene de JobActionNotFound.__str__()
    assert "Job action not found" in payload["payload"]["data"]


def test_job_management_wraps_specific_error_types_in_payload():
    docker = MagicMock()
    triton = MagicMock()
    openstack = MagicMock()
    sent, ws = _make_ws_collector()

    jm = JobManagement(
        docker=docker,
        triton=triton,
        openstack=openstack,
        websocket=ws,
        management_actions_available=["creation"],
    )

    # Force a specific exception from the pipeline handler (e.g. DockerAPIError)
    from classes.docker.dockererrors import DockerAPIError

    def raise_docker_api(*_args, **_kwargs):
        raise DockerAPIError("boom")

    jm.creation = raise_docker_api

    msg = {"uuid": "u2", "payload": {"action": "creation"}}
    jm.handle_management(msg)

    assert len(sent) == 1
    uuid, payload = sent[0]
    assert uuid == "u2"
    assert payload["payload"]["status"] is False
    assert "boom" in payload["payload"]["data"]


def test_job_inference_http_success_and_failed_protocol():
    # Prepare fake TritonThread with TritonInfer and HTTP handler
    triton_thread = MagicMock()
    triton_thread.triton_infer = TritonInfer()

    docker = MagicMock()
    openstack = MagicMock()
    sent, ws = _make_ws_collector()

    ji = JobInference(
        triton=triton_thread,
        docker=docker,
        openstack=openstack,
        websocket=ws,
        inference_actions_available=[],
    )

    # Stub HTTP handler
    http_handler = MagicMock()
    http_handler.handle.return_value = {"result": 1}
    ji._http = http_handler
    ji._grpc = MagicMock()

    msg = {
        "uuid": "u-http",
        "type": "inference",
        "payload": {
            "model_name": "m",
            "request": {"protocol": "http"},
        },
    }

    ji.handle_inference(msg)

    # HTTP path should produce one COMPLETED message
    out = [p for u, p in sent if u == "u-http"]
    assert len(out) == 1
    assert out[0]["payload"]["status"] == "COMPLETED"
    assert out[0]["payload"]["data"] == {"result": 1}

    # Unsupported protocol
    sent.clear()
    bad_msg = {
        "uuid": "u-bad",
        "type": "inference",
        "payload": {"model_name": "m", "request": {"protocol": "smtp"}},
    }
    ji.handle_inference(bad_msg)
    out_bad = [p for u, p in sent if u == "u-bad"]
    assert len(out_bad) == 1
    assert out_bad[0]["payload"]["status"] == "FAILED"
    assert "Unsupported inference protocol" in out_bad[0]["payload"]["data"]


def test_job_inference_missing_uuid_and_errors():
    triton_thread = MagicMock()
    triton_thread.triton_infer = TritonInfer()
    docker = MagicMock()
    openstack = MagicMock()
    sent, ws = _make_ws_collector()

    ji = JobInference(
        triton=triton_thread,
        docker=docker,
        openstack=openstack,
        websocket=ws,
        inference_actions_available=[],
    )

    # Missing uuid should raise JobInferenceMissingField before sending anything
    with pytest.raises(JobInferenceMissingField):
        ji.handle_inference({"type": "inference", "payload": {}})

    assert sent == []

    # Simulate JobInferenceMissingField from handler
    ji._http = MagicMock()
    ji._grpc = MagicMock()

    def raise_missing(*args, **kwargs):
        raise JobInferenceMissingField("model_name")

    ji._http.handle.side_effect = raise_missing
    msg = {
        "uuid": "u2",
        "type": "inference",
        "payload": {"model_name": None, "request": {"protocol": "http"}},
    }
    ji.handle_inference(msg)
    out = [p for u, p in sent if u == "u2"]
    assert len(out) == 1
    assert out[0]["payload"]["status"] == "FAILED"
    assert "model_name" in out[0]["payload"]["data"]

    # Simulate TritonInferenceFailed
    sent.clear()

    def raise_triton(*args, **kwargs):
        raise TritonInferenceFailed("m", "boom")

    ji._http.handle.side_effect = raise_triton

    ji.handle_inference(
        {
            "uuid": "u3",
            "type": "inference",
            "payload": {"model_name": "m", "request": {"protocol": "http"}},
        }
    )
    out2 = [p for u, p in sent if u == "u3"]
    assert len(out2) == 1
    assert out2[0]["payload"]["status"] == "FAILED"
    assert out2[0]["payload"]["model_name"] == "m"
