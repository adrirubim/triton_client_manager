from unittest.mock import MagicMock

from classes.triton.info.data.server import TritonServer
from classes.triton.tritonerrors import TritonMissingArgument, TritonMissingInstance
from classes.triton.tritonthread import TritonThread


def _make_config():
    return {
        "refresh_time": 0.01,
        "health_check_timeout": 1,
        "triton_models_path": "/models",
        "minio": {},
    }


def test_triton_thread_load_and_alert(monkeypatch):
    cfg = _make_config()
    t = TritonThread(cfg)

    # dict_servers with one server transitioning from unhealthy to healthy
    server = TritonServer(
        vm_id="vm1",
        vm_ip="10.0.0.5",
        container_id="cid-1",
        client=MagicMock(),
        model_name="m",
    )
    server.status = "unhealthy"
    t.dict_servers[("vm1", "cid-1")] = server

    t.triton_info.is_server_ready = MagicMock(return_value=True)

    alerts = []

    def ws(msg):
        alerts.append(msg)
        return True

    t.websocket = ws

    t.load()

    assert server.status == "ready"
    assert alerts
    assert alerts[0]["error_type"] == "TritonServerStateChanged"


def test_triton_thread_create_and_delete_server(monkeypatch):
    cfg = _make_config()
    t = TritonThread(cfg)

    fake_server = TritonServer(
        vm_id="vm1",
        vm_ip="10.0.0.5",
        container_id="cid-1",
        client=MagicMock(),
    )

    # triton_creation returns a TritonServer instance
    t.triton_creation.handle = MagicMock(return_value=fake_server)

    data = {"vm_id": "vm1", "vm_ip": "10.0.0.5", "minio": {}, "container_id": "cid-1"}
    created = t.create_server(data.copy())
    assert created is fake_server
    assert t.dict_servers[("vm1", "cid-1")] is fake_server

    # If a server already exists for that key, it must be closed
    old_server = TritonServer(
        vm_id="vm1",
        vm_ip="10.0.0.5",
        container_id="cid-1",
        client=MagicMock(),
    )
    old_server.close = MagicMock()
    t.dict_servers[("vm1", "cid-1")] = old_server
    t.create_server(data.copy())
    old_server.close.assert_called_once()

    # delete_server happy path
    t.triton_deletion.handle = MagicMock()
    out = t.delete_server({"vm_id": "vm1", "container_id": "cid-1"})
    assert out["vm_id"] == "vm1"

    # delete_server when the server does not exist
    try:
        t.delete_server({"vm_id": "vm1", "container_id": "cid-unknown"})
        assert False, "expected TritonMissingInstance"
    except TritonMissingInstance:
        pass

    # Ensure create_server and delete_server validate required arguments
    for bad in [
        {},
        {"vm_id": "vm1"},
        {"vm_id": "vm1", "vm_ip": "x"},
        {"vm_id": "vm1", "vm_ip": "x", "minio": {}},
    ]:
        try:
            t.create_server(bad)
            assert False, "expected TritonMissingArgument"
        except TritonMissingArgument:
            pass
