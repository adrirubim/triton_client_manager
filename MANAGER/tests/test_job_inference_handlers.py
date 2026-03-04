from unittest.mock import MagicMock

import pytest

from classes.job.inference.handlers.base import check_instance, validate_fields
from classes.job.inference.handlers.grpc import JobInferenceGrpc
from classes.job.inference.handlers.http import JobInferenceHttp
from classes.triton.tritonerrors import TritonInferenceFailed


def test_check_instance_and_validate_fields_errors():
    docker = MagicMock()
    docker.dict_containers = {}

    with pytest.raises(ValueError):
        check_instance(docker, "10.0.0.5", "cid")

    # Bad vm_ip vs container.worker_ip
    c = MagicMock()
    c.worker_ip = "10.0.0.6"
    docker.dict_containers = {"cid": c}
    with pytest.raises(ValueError):
        check_instance(docker, "10.0.0.5", "cid")

    # validate_fields missing pieces
    with pytest.raises(ValueError):
        validate_fields({})
    with pytest.raises(ValueError):
        validate_fields({"vm_ip": "x"})
    with pytest.raises(ValueError):
        validate_fields({"vm_ip": "x", "container_id": "c"})
    with pytest.raises(ValueError):
        validate_fields({"vm_ip": "x", "container_id": "c", "model_name": "m"})
    # ok path
    vm_ip, cid, model_name, inputs = validate_fields(
        {
            "vm_ip": "x",
            "container_id": "c",
            "model_name": "m",
            "request": {"inputs": [1]},
        }
    )
    assert (vm_ip, cid, model_name, inputs) == ("x", "c", "m", [1])


def _basic_payload():
    return {
        "vm_ip": "10.0.0.5",
        "container_id": "cid-1",
        "model_name": "m",
        "request": {"inputs": [1, 2, 3]},
    }


def test_http_handler_happy_and_errors():
    docker = MagicMock()
    container = MagicMock()
    container.worker_ip = "10.0.0.5"
    docker.dict_containers = {"cid-1": container}

    triton_infer = MagicMock()
    triton_infer.infer.return_value = {"outputs": [b"ok"]}

    # Use a fake static decode_response
    def fake_decode(resp):
        assert resp == {"outputs": [b"ok"]}
        return {"decoded": True}

    # Patch the static method inside the class
    from classes.triton import infer as triton_infer_module

    old_decode = triton_infer_module.TritonInfer.decode_response
    triton_infer_module.TritonInfer.decode_response = staticmethod(fake_decode)

    triton = MagicMock()
    server = MagicMock()
    triton.get_server.return_value = server

    handler = JobInferenceHttp(docker, triton_infer, triton)
    sent = []

    def send(status, data=None, model_name=None):
        sent.append((status, data, model_name))

    decoded = handler.handle("uuid", _basic_payload(), send)
    assert decoded == {"decoded": True}
    triton_infer.infer.assert_called_once_with(server.client, "m", [1, 2, 3])

    # Without TritonThread it must raise TritonInferenceFailed
    handler_no_triton = JobInferenceHttp(docker, triton_infer, None)
    with pytest.raises(TritonInferenceFailed):
        handler_no_triton.handle("uuid", _basic_payload(), send)

    # Without an active server
    triton.get_server.return_value = None
    handler_missing = JobInferenceHttp(docker, triton_infer, triton)
    with pytest.raises(TritonInferenceFailed):
        handler_missing.handle("uuid", _basic_payload(), send)

    # Restaurar decode_response
    triton_infer_module.TritonInfer.decode_response = old_decode


def test_grpc_handler_streams_start_ongoing_and_errors():
    docker = MagicMock()
    container = MagicMock()
    container.worker_ip = "10.0.0.5"
    docker.dict_containers = {"cid-1": container}

    triton_infer = MagicMock()

    triton = MagicMock()
    server = MagicMock()
    triton.get_server.return_value = server

    handler = JobInferenceGrpc(docker, triton_infer, triton)
    sent = []

    def send(status, data=None, model_name=None):
        sent.append((status, data, model_name))

    def fake_stream(client, model_name, inputs, on_chunk, output_name):
        on_chunk({"chunk": 1})
        on_chunk({"chunk": 2})

    triton_infer.stream.side_effect = fake_stream

    handler.handle(
        "uuid",
        {**_basic_payload(), "request": {"inputs": [1], "output_name": "out"}},
        send,
    )

    # There must be one START and several ONGOING statuses
    statuses = [s for s, *_ in sent]
    assert statuses[0] == "START"
    assert statuses[1:] == ["ONGOING", "ONGOING"]

    # Without TritonThread
    handler_no_triton = JobInferenceGrpc(docker, triton_infer, None)
    with pytest.raises(TritonInferenceFailed):
        handler_no_triton.handle("uuid", _basic_payload(), send)

    # Without an active server
    triton.get_server.return_value = None
    handler_missing = JobInferenceGrpc(docker, triton_infer, triton)
    with pytest.raises(TritonInferenceFailed):
        handler_missing.handle("uuid", _basic_payload(), send)
