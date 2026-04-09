from unittest.mock import MagicMock

import pytest

from classes.openstack.info.data.vm import VM
from classes.openstack.openstackerrors import (
    OpenstackCreationMissingKey,
    OpenstackDeletionMissingVM,
    OpenstackMissingArgument,
    OpenstackResourceNotFound,
)
from classes.openstack.openstackthread import OpenstackThread


def _base_kwargs():
    return {
        "refresh_time": 0.01,
        "creation_variables": [
            "name",
            "image_id",
            "flavor_id",
            "network_id",
            "keypair",
            "security",
        ],
        "auth_url": "http://keystone",
        "project_name": "p",
        "username": "u",
        "password": "pw",
        "user_domain_name": "Default",
        "project_domain_name": "Default",
        "region_name": "RegionOne",
        "verify_ssl": False,
        "info_endpoints": {},
        "creation_timeout": 1,
        "creation_endpoint": "http://nova",
        "deletion_timeout": 1,
        "deletion_endpoint": "http://nova",
    }


def test_openstack_thread_load_and_alert(monkeypatch):
    kwargs = _base_kwargs()

    # Avoid real auth calls
    fake_auth = MagicMock()
    fake_auth.authenticate.return_value = True
    fake_auth.check_and_refresh_token = MagicMock()
    monkeypatch.setattr("classes.openstack.openstackthread.OpenstackAuth", lambda **_: fake_auth)

    t = OpenstackThread(**kwargs)

    # Simulate info for VMs and related resources
    vm_old = VM(
        id="vm1",
        name="vm",
        status="ACTIVE",
        user_id="u",
        project_id="p",
        host_id="h",
        host_name="hh",
        image_id="img",
        flavor_name="flv",
        address_private="10.0.0.5",
        mac_public=None,
        mac_private=None,
        address_public=None,
        created="",
        launched=None,
        terminated=None,
    )
    vm_new = VM(**{**vm_old.__dict__, "status": "ERROR"})

    # Initially dict_vms contains vm_old
    t.dict_vms = {"vm1": vm_old}

    info = MagicMock()
    info.load_vms.return_value = {"vm1": vm_new}
    info.load_images.return_value = {}
    info.load_flavors.return_value = {}
    info.load_networks.return_value = {}
    info.load_keypairs.return_value = {}
    info.load_security.return_value = {}
    t.openstack_info = info

    alerts = []

    def ws(msg):
        alerts.append(msg)
        return True

    t.websocket = ws

    t.load()

    # vm_new must replace vm_old and alerts must be sent
    assert t.dict_vms["vm1"].status == "ERROR"
    assert alerts
    assert alerts[0]["error_type"] == "OpenstackVMStateChanged"


def test_openstack_thread_create_and_delete_vm(monkeypatch):
    kwargs = _base_kwargs()
    fake_auth = MagicMock()
    fake_auth.authenticate.return_value = True
    fake_auth.check_and_refresh_token = MagicMock()
    monkeypatch.setattr("classes.openstack.openstackthread.OpenstackAuth", lambda **_: fake_auth)

    t = OpenstackThread(**kwargs)

    # Prepare dictionaries to satisfy resource validations
    with t._data_lock:
        t.dict_keypairs = {"kp": MagicMock()}
        t.dict_images = {"img": MagicMock()}
        t.dict_securities = {"sec": MagicMock()}
        t.dict_flavors = {"flv": MagicMock()}
        t.dict_networks = {"net": MagicMock()}

    t.openstack_creation.handle = MagicMock(return_value=("10.0.0.5", "vm1"))

    vm_loaded = MagicMock(spec=VM)
    vm_loaded.id = "vm1"
    vm_loaded.status = "ACTIVE"
    t.openstack_info.load_single_vm = MagicMock(return_value=vm_loaded)

    payload = {
        "name": "vm",
        "image_id": "img",
        "flavor_id": "flv",
        "network_id": "net",
        "keypair": "kp",
        "security": "sec",
    }
    ip, vm_id = t.create_vm(payload.copy())
    assert vm_id == "vm1"
    assert t.dict_vms["vm1"] is vm_loaded

    # delete_vm happy path
    t.openstack_deletion.handle = MagicMock()
    out = t.delete_vm({"vm_id": "vm1"})
    assert out["vm_id"] == "vm1"
    assert "vm1" not in t.dict_vms

    # delete_vm with non‑existing vm
    with pytest.raises(OpenstackDeletionMissingVM):
        t.delete_vm({"vm_id": "vm-unknown"})

    # Ensure create_vm validations are enforced
    with pytest.raises(OpenstackCreationMissingKey):
        t.create_vm({})

    # Missing resources in dictionaries
    with t._data_lock:
        t.dict_keypairs = {}
    with pytest.raises(OpenstackResourceNotFound):
        t.create_vm(payload.copy())

    # Ensure OpenstackMissingArgument is raised in delete_vm
    with pytest.raises(OpenstackMissingArgument):
        t.delete_vm({})
