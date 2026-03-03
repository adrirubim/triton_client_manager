from unittest.mock import MagicMock

from classes.triton.info.info import TritonInfo


def _fake_client():
    c = MagicMock()
    c.is_server_ready.return_value = True
    c.is_model_ready.return_value = True
    c.get_server_metadata.return_value = {"ready": True}
    c.get_model_metadata.return_value = {"name": "m"}
    return c


def test_triton_info_health_and_metadata(monkeypatch):
    info = TritonInfo(timeout=1, http_port=8000)

    def fake_client(vm_ip, timeout=None):
        assert vm_ip == "10.0.0.5"
        return _fake_client()

    monkeypatch.setattr(info, "_client", fake_client)

    assert info.is_server_ready("10.0.0.5") is True
    assert info.is_model_ready("10.0.0.5", "m") is True
    assert info.get_server_metadata("10.0.0.5") == {"ready": True}
    assert info.get_model_metadata("10.0.0.5", "m") == {"name": "m"}


def test_triton_info_wait_and_model_management(monkeypatch):
    info = TritonInfo(timeout=1, http_port=8000)

    client = _fake_client()

    def fake_client(vm_ip, timeout=None):
        return client

    monkeypatch.setattr(info, "_client", fake_client)

    # wait_for_server_ready / wait_for_model_ready exit quickly because they return True
    assert info.wait_for_server_ready("10.0.0.5", timeout=1) is True
    assert info.wait_for_model_ready("10.0.0.5", "m", timeout=1) is True

    # load/unload model happy path
    assert info.load_model("10.0.0.5", "m", timeout=1, config_json="{}") is True
    assert info.unload_model("10.0.0.5", "m", timeout=1) is True

    # Also cover the error branch returning False
    def raising_client(vm_ip, timeout=None):
        c = MagicMock()
        c.load_model.side_effect = RuntimeError("boom")
        c.unload_model.side_effect = RuntimeError("boom")
        return c

    monkeypatch.setattr(info, "_client", raising_client)
    assert info.load_model("10.0.0.5", "m") is False
    assert info.unload_model("10.0.0.5", "m") is False
