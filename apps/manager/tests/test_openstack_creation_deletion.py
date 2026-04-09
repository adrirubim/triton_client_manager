from unittest.mock import MagicMock

import pytest

from classes.openstack.creation.creation import OpenstackCreation
from classes.openstack.deletion.deletion import OpenstackDeletion
from classes.openstack.openstackerrors import (
    OpenstackDeletionError,
    OpenstackDeletionMissingVM,
    OpenstackDeletionTimeout,
)


def _fake_auth():
    catalog = MagicMock()
    compute = MagicMock()
    compute.endpoint_internal = "http://compute.internal"
    catalog.compute = compute

    auth = MagicMock()
    auth.token = "t"
    auth.verify_ssl = False
    auth.catalog = catalog
    return auth


def test_openstack_creation_handle_calls_post_and_loop_status(monkeypatch):
    auth = _fake_auth()
    oc = OpenstackCreation(auth, timeout=5, endpoint="/servers")

    class DummyResp:
        def __init__(self, json_data):
            self._json = json_data

        def raise_for_status(self):
            return None

        def json(self):
            return self._json

    captured = {}

    def fake_post(url, json, verify, timeout, headers):
        captured["url"] = url
        captured["json"] = json
        assert url == "http://compute.internal/servers"
        return DummyResp({"server": {"id": "vm1"}})

    monkeypatch.setattr("classes.openstack.creation.creation.requests.post", fake_post)
    monkeypatch.setattr(oc, "loop_status", lambda vm_id: "10.0.0.5")

    ip, vm_id = oc.handle(
        name="vm",
        keypair="kp",
        image_id="img",
        security="sec",
        flavor_id="flv",
        network_id="net",
        config_drive=False,
    )
    assert vm_id == "vm1"
    assert ip == "10.0.0.5"
    assert captured["json"]["server"]["name"] == "vm"


def test_openstack_creation_loop_status_error_and_timeout(monkeypatch):
    auth = _fake_auth()
    oc = OpenstackCreation(auth, timeout=3, endpoint="/servers")

    class DummyResp:
        def __init__(self, data):
            self._data = data

        def json(self):
            return {"server": self._data}

    # Error case: status ERROR should return None
    def fake_get_err(url, verify, timeout, headers):
        return DummyResp({"status": "ERROR", "ip": ""})

    # For this case we keep the real time.time so it hits the except and returns None
    import time as real_time

    monkeypatch.setattr("classes.openstack.creation.creation.time.time", real_time.time)
    monkeypatch.setattr("classes.openstack.creation.creation.requests.get", fake_get_err)
    ip_err = oc.loop_status("vm2")
    assert ip_err is None

    # Timeout case: never ACTIVE within configured timeout, returns None
    def fake_get_build(url, verify, timeout, headers):
        return DummyResp({"status": "BUILD", "ip": ""})

    # Simulate a timeout by repeating the loop several times without ACTIVE
    monkeypatch.setattr("classes.openstack.creation.creation.requests.get", fake_get_build)
    ip_timeout = oc.loop_status("vm3")
    assert ip_timeout is None


def test_openstack_deletion_handle_happy_and_404(monkeypatch):
    auth = _fake_auth()
    od = OpenstackDeletion(auth, timeout=3, endpoint="/servers")

    class DummyResp:
        def __init__(self, status_code=204):
            self.status_code = status_code

        def raise_for_status(self):
            if 400 <= self.status_code < 500 and self.status_code != 404:
                raise requests.exceptions.HTTPError(response=self)

    import requests

    calls = {"delete": 0, "get": []}

    def fake_delete(url, verify, timeout, headers):
        calls["delete"] += 1
        return DummyResp(204)

    def fake_get(url, verify, timeout, headers):
        # Always return 404 to simulate VM already deleted
        resp = DummyResp(404)
        calls["get"].append(resp.status_code)
        return resp

    monkeypatch.setattr("classes.openstack.deletion.deletion.requests.delete", fake_delete)
    monkeypatch.setattr("classes.openstack.deletion.deletion.requests.get", fake_get)

    od.handle("vm1")
    assert calls["delete"] == 1
    assert calls["get"] == [404]

    # 404 on delete should map to OpenstackDeletionMissingVM
    def fake_delete_404(url, verify, timeout, headers):
        resp = DummyResp(404)
        raise requests.exceptions.HTTPError(response=resp)

    monkeypatch.setattr("classes.openstack.deletion.deletion.requests.delete", fake_delete_404)
    with pytest.raises(OpenstackDeletionMissingVM):
        od.handle("vm-missing")


def test_openstack_deletion_timeout_and_errors(monkeypatch):
    auth = _fake_auth()
    od = OpenstackDeletion(auth, timeout=2, endpoint="/servers")

    import time as real_time

    class DummyResp:
        def __init__(self, status_code):
            self.status_code = status_code

        def raise_for_status(self):
            return None

    def fake_delete(url, verify, timeout, headers):
        return DummyResp(204)

    start = real_time.time()

    def fake_time():
        nonlocal start
        start += 2
        return start

    def fake_get(url, verify, timeout, headers):
        # Nunca devuelve 404 -> fuerza timeout
        return DummyResp(200)

    monkeypatch.setattr("classes.openstack.deletion.deletion.requests.delete", fake_delete)
    monkeypatch.setattr("classes.openstack.deletion.deletion.requests.get", fake_get)
    monkeypatch.setattr("classes.openstack.deletion.deletion.time.time", fake_time)

    with pytest.raises(OpenstackDeletionTimeout):
        od.handle("vm-timeout")

    # Generic error on delete should be mapped to OpenstackDeletionError
    def delete_raises(url, verify, timeout, headers):
        raise RuntimeError("boom")

    monkeypatch.setattr("classes.openstack.deletion.deletion.requests.delete", delete_raises)
    with pytest.raises(OpenstackDeletionError):
        od.handle("vm-err")
