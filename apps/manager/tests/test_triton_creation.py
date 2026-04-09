import json
from unittest.mock import MagicMock, patch

import pytest

from classes.triton.constants import GRPC_PORT, HTTP_PORT
from classes.triton.creation.creation import TritonCreation
from classes.triton.info.data.server import TritonServer
from classes.triton.tritonerrors import (
    TritonConfigDownloadFailed,
    TritonModelLoadFailed,
    TritonModelNotReady,
    TritonServerHealthFailed,
)

_PBTXT_TEMPLATE = """
name: "my_model"
input {{
  name: "input_ids"
  data_type: TYPE_INT64
  dims: 128
}}
output {{
  name: "output_ids"
  data_type: TYPE_INT64
  dims: 128
}}
model_transaction_policy {{
  decoupled: {decoupled}
}}
"""


def _make_minio_and_params(decoupled: bool = False):
    minio = {
        "endpoint": "http://minio:9000",
        "access_key": "key",
        "secret_key": "secret",
        "bucket": "models",
        "folder": "mymodel",
    }
    triton_params = {"max_batch_size": "8"}
    pbtxt = _PBTXT_TEMPLATE.format(decoupled="true" if decoupled else "false")
    return minio, triton_params, pbtxt


@patch("classes.triton.creation.creation.boto3.client")
def test_download_pbtxt_success(mock_client):
    """_download_pbtxt should read and decode config.pbtxt from MinIO."""
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": MagicMock(read=lambda: b"content")}
    mock_client.return_value = s3

    tc = TritonCreation({})
    minio, _, _ = _make_minio_and_params()

    out = tc._download_pbtxt("mymodel/mymodel/config.pbtxt", minio)
    assert out == "content"
    mock_client.assert_called_once()


@patch("classes.triton.creation.creation.boto3.client")
def test_download_pbtxt_failure_raises_config_error(mock_client):
    """Errors from boto3 client should raise TritonConfigDownloadFailed."""
    mock_client.side_effect = RuntimeError("boom")

    tc = TritonCreation({})
    minio, _, _ = _make_minio_and_params()

    with pytest.raises(TritonConfigDownloadFailed) as exc:
        tc._download_pbtxt("mymodel/mymodel/config.pbtxt", minio)
    assert "boom" in str(exc.value)


def test_pbtxt_to_config_builds_schema_and_selects_http_or_grpc():
    """_pbtxt_to_config should convert pbtxt to JSON config and choose port based on decoupled flag."""
    tc = TritonCreation({})
    _, params, pbtxt_http = _make_minio_and_params(decoupled=False)
    config_json, inputs, outputs, model_name, port = tc._pbtxt_to_config(params, pbtxt_http)

    cfg = json.loads(config_json)
    assert cfg["name"] == "my_model"
    assert model_name == "my_model"
    assert len(inputs) == 1 and inputs[0]["name"] == "input_ids"
    assert len(outputs) == 1 and outputs[0]["name"] == "output_ids"
    assert port == HTTP_PORT

    _, params2, pbtxt_grpc = _make_minio_and_params(decoupled=True)
    _, _, _, _, port2 = tc._pbtxt_to_config(params2, pbtxt_grpc)
    assert port2 == GRPC_PORT


@patch.object(TritonCreation, "_download_pbtxt")
@patch.object(TritonCreation, "_pbtxt_to_config")
def test_process_config_builds_key_and_allows_empty_params(mock_pbtxt_to_config, mock_download):
    """_process_config should compute S3 key correctly and null config_json when no triton_params."""
    tc = TritonCreation({})
    minio, params, pbtxt = _make_minio_and_params()

    mock_download.return_value = pbtxt
    mock_pbtxt_to_config.return_value = (
        "{}",
        [{"name": "i"}],
        [{"name": "o"}],
        "m",
        HTTP_PORT,
    )

    config_json, inputs, outputs, model_name, port = tc._process_config(minio, params)
    assert config_json == "{}"
    assert model_name == "m"
    assert inputs and outputs
    mock_download.assert_called_once()

    # When triton_params is empty, config_json must be None
    config_json2, *_ = tc._process_config(minio, {})
    assert config_json2 is None


@patch("classes.triton.creation.creation.httpclient.InferenceServerClient")
@patch.object(TritonCreation, "_process_config")
def test_handle_happy_path_http(mock_process_config, mock_http_client_cls):
    """handle should wait for readiness, load model and return TritonServer."""
    tc = TritonCreation(
        {
            "client_request_timeout": 5,
            "server_ready_timeout": 1,
            "model_ready_timeout": 1,
        }
    )

    mock_process_config.return_value = (
        "{}",
        [{"name": "i"}],
        [{"name": "o"}],
        "my_model",
        HTTP_PORT,
    )

    client = MagicMock()
    client.is_server_ready.return_value = True
    client.is_model_ready.return_value = True
    mock_http_client_cls.return_value = client

    server = tc.handle(
        vm_id="vm-1",
        vm_ip="10.0.0.1",
        minio={},
        triton={},
        container_id="cid-1234567890ab",
    )

    assert isinstance(server, TritonServer)
    assert server.vm_id == "vm-1"
    assert server.vm_ip == "10.0.0.1"
    assert server.model_name == "my_model"
    client.is_server_ready.assert_called()
    client.load_model.assert_called_once()
    client.is_model_ready.assert_called()


@patch("classes.triton.creation.creation.httpclient.InferenceServerClient")
@patch.object(TritonCreation, "_process_config")
def test_handle_missing_model_name_or_io_raises(mock_process_config, mock_http_client_cls):
    """handle should raise TritonModelLoadFailed when model_name/inputs/outputs are missing."""
    tc = TritonCreation({})

    # No model_name
    mock_process_config.return_value = ("{}", [{"n": "i"}], [{"n": "o"}], "", HTTP_PORT)
    with pytest.raises(TritonModelLoadFailed):
        tc.handle("vm", "ip", {}, {}, "cid")

    # No inputs
    mock_process_config.return_value = ("{}", [], [{"name": "o"}], "m", HTTP_PORT)
    with pytest.raises(TritonModelLoadFailed):
        tc.handle("vm", "ip", {}, {}, "cid")

    # No outputs
    mock_process_config.return_value = ("{}", [{"name": "i"}], [], "m", HTTP_PORT)
    with pytest.raises(TritonModelLoadFailed):
        tc.handle("vm", "ip", {}, {}, "cid")

    assert not mock_http_client_cls.called


@patch("classes.triton.creation.creation.httpclient.InferenceServerClient")
@patch.object(TritonCreation, "_process_config")
def test_handle_server_not_ready_raises_health_failed(mock_process_config, mock_http_client_cls):
    """If server never reports ready before timeout, TritonServerHealthFailed is raised."""
    tc = TritonCreation({"server_ready_timeout": 0})

    mock_process_config.return_value = (
        "{}",
        [{"name": "i"}],
        [{"name": "o"}],
        "m",
        HTTP_PORT,
    )

    client = MagicMock()
    client.is_server_ready.return_value = False
    mock_http_client_cls.return_value = client

    with pytest.raises(TritonServerHealthFailed):
        tc.handle("vm", "ip", {}, {}, "cid")


@patch("classes.triton.creation.creation.httpclient.InferenceServerClient")
@patch.object(TritonCreation, "_process_config")
def test_handle_load_model_failure_raises_model_load_failed(mock_process_config, mock_http_client_cls):
    """If load_model throws, TritonModelLoadFailed should be raised."""
    tc = TritonCreation({})

    mock_process_config.return_value = (
        "{}",
        [{"name": "i"}],
        [{"name": "o"}],
        "m",
        HTTP_PORT,
    )

    client = MagicMock()
    client.is_server_ready.return_value = True
    client.load_model.side_effect = RuntimeError("boom")
    mock_http_client_cls.return_value = client

    with pytest.raises(TritonModelLoadFailed):
        tc.handle("vm", "ip", {}, {}, "cid")


@patch("classes.triton.creation.creation.httpclient.InferenceServerClient")
@patch.object(TritonCreation, "_process_config")
def test_handle_model_not_ready_raises_not_ready(mock_process_config, mock_http_client_cls):
    """If model never becomes ready, TritonModelNotReady should be raised."""
    tc = TritonCreation({"model_ready_timeout": 0})

    mock_process_config.return_value = (
        "{}",
        [{"name": "i"}],
        [{"name": "o"}],
        "m",
        HTTP_PORT,
    )

    client = MagicMock()
    client.is_server_ready.return_value = True
    client.is_model_ready.return_value = False
    mock_http_client_cls.return_value = client

    with pytest.raises(TritonModelNotReady):
        tc.handle("vm", "ip", {}, {}, "cid")
