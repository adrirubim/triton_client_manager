from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from classes.websocket.schemas import (
    AuthMessage,
    BaseMessage,
    InferenceInputsEntry,
    InferenceMessage,
    InfoMessage,
    ManagementMessage,
)
from utils.logging_config import configure_logging
from utils.metrics import (
    JOB_PROCESSING_SECONDS,
    JOBS_REJECTED_TOTAL,
    WS_MESSAGES_TOTAL,
    generate_metrics_response,
    observe_job_processing,
    observe_job_rejected,
    observe_ws_message,
)


def test_websocket_schemas_happy_paths_and_validation():
    # BaseMessage validates top-level envelope and allowed types
    base = BaseMessage(uuid="u1", type="auth", payload={})
    assert base.uuid == "u1"
    assert base.type == "auth"

    # AuthMessage defaults payload to {}
    auth = AuthMessage(uuid="u2")
    assert auth.type == "auth"
    assert auth.payload == {}

    # InfoMessage wraps InfoPayload and defaults action to queue_stats
    info = InfoMessage(uuid="u3", payload={})
    assert info.type == "info"
    assert info.payload.action == "queue_stats"

    # ManagementMessage requires action and sub‑payloads
    mgmt = ManagementMessage(
        uuid="u4",
        payload={
            "action": "creation",
            "openstack": {"x": 1},
            "docker": {},
            "minio": {},
        },
    )
    assert mgmt.type == "management"
    assert mgmt.payload.action == "creation"
    assert mgmt.payload.openstack["x"] == 1

    # InferenceMessage with HTTP request config and inputs list
    inputs = [
        InferenceInputsEntry(
            name="input_1", type="FP32", dims=[1, 3], value=[0.1, 0.2]
        ),
    ]
    inf = InferenceMessage(
        uuid="u5",
        payload={
            "vm_id": "vm-1",
            "container_id": "c-1",
            "model_name": "m1",
            "inputs": [i.model_dump() for i in inputs],
        },
    )
    assert inf.type == "inference"
    assert inf.payload.model_name == "m1"
    assert inf.payload.request.protocol == "http"
    assert inf.payload.inputs[0].name == "input_1"


def test_websocket_schemas_reject_invalid_type():
    # BaseMessage only allows the four known types
    from pydantic import ValidationError

    try:
        BaseMessage(uuid="u", type="unknown", payload={})
    except ValidationError as exc:  # noqa: PERF203
        errors = str(exc)
        assert "literal" in errors or "One of" in errors
    else:  # pragma: no cover - defensive
        raise AssertionError("BaseMessage accepted an unknown type")


def test_metrics_observe_and_generate_response_with_stats_and_failure(monkeypatch):
    # Observe a couple of messages and ensure labels are created
    observe_ws_message("auth")
    observe_ws_message("info")
    sample = WS_MESSAGES_TOTAL.collect()[0]
    # There should be at least two samples, one per type
    labels = {s.labels["type"] for s in sample.samples}
    assert {"auth", "info"}.issubset(labels)

    # Successful stats path
    def fake_stats():
        return {
            "total_users": 3,
            "total_queued": 7,
            "info_users": 1,
            "management_users": 1,
            "inference_users": 1,
            "info_total_queued": 2,
            "management_total_queued": 3,
            "inference_total_queued": 2,
            "executor_info_pending": 1,
            "executor_management_pending": 2,
            "executor_inference_pending": 4,
            "executor_info_available": 5,
            "executor_management_available": 6,
            "executor_inference_available": 7,
        }

    response = generate_metrics_response(fake_stats)
    assert response.status_code == 200
    body = response.body.decode("utf-8")
    # A couple of key gauges must be present
    assert "tcm_queue_total_users" in body
    assert "tcm_executor_info_available" in body

    # Error path: stats function raises, endpoint must still work and not crash
    def boom():
        raise RuntimeError("stats failed")

    response2 = generate_metrics_response(boom)
    assert response2.status_code == 200


def test_job_metrics_rejected_and_processing_histogram():
    # Rejected jobs counter should track rejections per type
    observe_job_rejected("info")
    observe_job_rejected("management")
    sample_rejected = JOBS_REJECTED_TOTAL.collect()[0]
    rejected_labels = {s.labels["type"] for s in sample_rejected.samples}
    assert {"info", "management"}.issubset(rejected_labels)

    # Processing histogram should accept observations and expose count samples
    observe_job_processing("inference", 0.01)
    sample_hist = JOB_PROCESSING_SECONDS.collect()[0]
    # Find the *_count sample to ensure at least one observation was recorded
    counts = [s for s in sample_hist.samples if s.name.endswith("_count")]
    assert any(s.labels.get("type") == "inference" and s.value >= 1 for s in counts)


def test_metrics_endpoint_and_logging_config_in_fastapi_app():
    # Configure logging; this must not raise even if no extra fields are provided.
    configure_logging()

    # Build a tiny FastAPI app using the shared generate_metrics_response
    app = FastAPI()

    @app.get("/metrics")
    def metrics_endpoint():
        # Use a minimal stats provider
        return generate_metrics_response(
            lambda: {"total_users": 1, "executor_info_available": 42}
        )

    client = TestClient(app)
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "tcm_queue_total_users" in res.text
    assert "tcm_executor_info_available" in res.text

    # If we reached this point without exceptions, logging configuration is compatible
    # with FastAPI/TestClient and the metrics endpoint contract is satisfied.
