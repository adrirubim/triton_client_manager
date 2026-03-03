from unittest.mock import MagicMock

from classes.docker.dockerthread import DockerThread


def _make_config():
    return {
        "refresh_time": 0.01,
        "registry_timeout": 1,
        "registry_endpoint": "http://registry.local",
        "registry_image_types": ["tritonserver"],
        "remote_api_timeout": 1,
        "remote_api_port": 2376,
    }


def test_docker_thread_load_populates_dicts_and_sends_alert(monkeypatch):
    cfg = _make_config()
    t = DockerThread(cfg)

    # Mock openstack with one VM and an existing container to detect change
    vm = MagicMock()
    vm.address_private = "10.0.0.5"
    t.openstack = MagicMock()
    t.openstack.dict_vms = {"vm1": vm}

    # First load_containers call returns an unchanged container, second returns a changed one
    old_c = MagicMock()
    old_c.worker_ip = "10.0.0.5"
    old_c.name = "ctr"
    old_c.has_changed.return_value = (False, [])

    new_c_same = MagicMock()
    new_c_same.worker_ip = "10.0.0.5"
    new_c_same.name = "ctr"
    new_c_same.has_changed.return_value = (False, [])

    new_c_changed = MagicMock()
    new_c_changed.worker_ip = "10.0.0.5"
    new_c_changed.name = "ctr"
    new_c_changed.has_changed.return_value = (True, ["status: running -> exited"])

    images_first = {"i1": object()}

    def fake_load_images():
        return images_first

    calls = {"step": 0}

    def fake_load_containers(dict_vms):
        # first call: no change, second: with change
        if calls["step"] == 0:
            calls["step"] += 1
            return {"c1": new_c_same}
        return {"c1": new_c_changed}

    t.docker_info.load_images = fake_load_images
    t.docker_info.load_containers = fake_load_containers

    alerts = []

    def ws(msg):
        alerts.append(msg)
        return True

    t.websocket = ws

    # First load: fills dict_images and dict_containers without alerts
    t.load()
    assert t.dict_images == images_first
    assert "c1" in t.dict_containers
    assert alerts == []

    # Second load: detects change and sends an alert
    # Simulate the previous container already existing in the dict
    t.dict_containers["c1"] = old_c
    t.load()
    assert alerts
    assert alerts[0]["type"] == "alert"
    assert alerts[0]["error_type"] == "DockerContainerStateChanged"


def test_docker_thread_create_and_delete_container(monkeypatch):
    cfg = _make_config()
    t = DockerThread(cfg)

    t.openstack = MagicMock()
    vm = MagicMock()
    vm.address_private = "10.0.0.5"
    t.openstack.dict_vms = {"vm1": vm}

    # Stub creation handler
    t.docker_creation.handle = MagicMock(return_value="cid-1")

    # Stub info.load_single_container
    fake_container = MagicMock()
    t.docker_info.load_single_container = MagicMock(return_value=fake_container)

    data = {
        "image": "tritonserver:24.01-py3",
        "worker_ip": "10.0.0.5",
        "env": {"A": "1"},
    }
    cid = t.create_container(data.copy())
    assert cid == "cid-1"
    assert t.dict_containers["cid-1"] is fake_container

    # Now delete_container uses dict_containers to obtain vm_ip
    t.docker_deletion.handle = MagicMock()
    delete_payload = {
        "vm_id": "vm1",
        "container_id": "cid-1",
        "force": True,
        "remove_volumes": True,
    }
    out = t.delete_container(delete_payload.copy())
    assert out["vm_id"] == "vm1"
    assert "cid-1" not in t.dict_containers
    t.docker_deletion.handle.assert_called_once()
