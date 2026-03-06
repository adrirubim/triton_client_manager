from unittest.mock import MagicMock

from classes.triton.info.info import TritonInfo


def test_triton_info_load_and_unload_model_error_paths():
    info = TritonInfo(timeout=1, http_port=8000)
    client = MagicMock()

    def fake_client(vm_ip: str, timeout: int | None = None):
        return client

    info._client = fake_client  # type: ignore[method-assign]

    # Successful calls
    assert info.load_model("10.0.0.1", "model-1", timeout=5, config_json="{}") is True
    client.load_model.assert_called_with("model-1", config="{}")

    assert info.unload_model("10.0.0.1", "model-1", timeout=5) is True
    client.unload_model.assert_called_with("model-1")

    # Failure branches
    client.load_model.side_effect = RuntimeError("boom")
    assert info.load_model("10.0.0.1", "model-2", timeout=5, config_json=None) is False

    client.unload_model.side_effect = RuntimeError("boom")
    assert info.unload_model("10.0.0.1", "model-2", timeout=5) is False


def test_triton_info_metadata_error_paths():
    info = TritonInfo(timeout=1, http_port=8000)
    client = MagicMock()

    def fake_client(vm_ip: str, timeout: int | None = None):
        return client

    info._client = fake_client  # type: ignore[method-assign]

    # Successful metadata calls
    client.get_server_metadata.return_value = {"name": "server"}
    client.get_model_metadata.return_value = {"name": "model"}

    assert info.get_server_metadata("10.0.0.1") == {"name": "server"}
    assert info.get_model_metadata("10.0.0.1", "model-1") == {"name": "model"}

    # Failure branches: exceptions are caught and {} returned
    client.get_server_metadata.side_effect = RuntimeError("server meta error")
    assert info.get_server_metadata("10.0.0.1") == {}

    client.get_model_metadata.side_effect = RuntimeError("model meta error")
    assert info.get_model_metadata("10.0.0.1", "model-1") == {}
