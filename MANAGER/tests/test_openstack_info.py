from unittest.mock import MagicMock

from classes.openstack.info.data.network import Network
from classes.openstack.info.data.vm import VM
from classes.openstack.info.info import OpenstackInfo


def _make_auth_and_catalog():
    catalog = MagicMock()
    compute = MagicMock()
    compute.endpoint_internal = "http://compute.internal"
    network = MagicMock()
    network.endpoint_internal = "http://network.internal"
    catalog.compute = compute
    catalog.network = network

    auth = MagicMock()
    auth.token = "t"
    auth.verify_ssl = False
    auth.catalog = catalog
    return auth


def test_openstack_info_load_vms_and_single_vm(monkeypatch):
    auth = _make_auth_and_catalog()
    endpoints = {
        "vms": {
            "service": "compute",
            "path": "/servers/detail",
            "data_class": "VM",
        }
    }
    info = OpenstackInfo(auth, endpoints)

    raw = {
        "servers": [
            {
                "id": "vm1",
                "name": "server-1",
                "OS-EXT-STS:vm_state": "active",
                "user_id": "u1",
                "tenant_id": "p1",
                "hostId": "h1",
                "OS-EXT-SRV-ATTR:hypervisor_hostname": "host-1",
                "image": {"id": "img1"},
                "flavor": {"original_name": "m1.large"},
                "addresses": {
                    "public": [
                        {
                            "version": 4,
                            "addr": "1.2.3.4",
                            "OS-EXT-IPS-MAC:mac_addr": "aa:bb:cc",
                        }
                    ],
                    "private": [
                        {
                            "version": 4,
                            "addr": "10.0.0.5",
                            "OS-EXT-IPS-MAC:mac_addr": "dd:ee:ff",
                        }
                    ],
                },
                "created": "2026-01-01T00:00:00Z",
                "OS-SRV-USG:launched_at": "2026-01-01T01:00:00Z",
                "OS-SRV-USG:terminated_at": None,
            }
        ]
    }

    def fake_execute(endpoint):
        assert endpoint == "http://compute.internal/servers/detail"
        return raw

    monkeypatch.setattr(info, "execute_request", fake_execute)

    vms = info.load_vms()
    assert "vm1" in vms
    vm = vms["vm1"]
    assert isinstance(vm, VM)
    assert vm.address_private == "10.0.0.5"
    assert vm.mac_public == "aa:bb:cc"

    # load_single_vm usa /{vm_id} y devuelve VM.from_id
    raw_single = {"server": raw["servers"][0]}

    def fake_single(endpoint):
        assert endpoint == "http://compute.internal/servers/vm1"
        return raw_single

    monkeypatch.setattr(info, "execute_request", fake_single)
    vm_one = info.load_single_vm("vm1")
    assert isinstance(vm_one, VM)
    assert vm_one.id == "vm1"


def test_openstack_info_networks_and_helper_get_vm_id_by_ip(monkeypatch):
    auth = _make_auth_and_catalog()
    endpoints = {
        "networks": {
            "service": "network",
            "path": "/v2.0/networks",
            "data_class": "Network",
        }
    }
    info = OpenstackInfo(auth, endpoints)

    raw_networks = {
        "networks": [
            {
                "id": "net1",
                "name": "public",
                "tenant_id": "t1",
                "project_id": "p1",
                "shared": True,
                "status": "ACTIVE",
                "subnets": ["sub1"],
                "router:internal": False,
                "router:external": True,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T01:00:00Z",
            }
        ]
    }

    def fake_exec(endpoint):
        assert endpoint == "http://network.internal/v2.0/networks"
        return raw_networks

    monkeypatch.setattr(info, "execute_request", fake_exec)
    nets = info.load_networks()
    assert "net1" in nets
    net = nets["net1"]
    assert isinstance(net, Network)
    assert net.router_external is True

    # Helper get_vm_id_by_ip
    vm1 = VM(
        id="vm1",
        name="n",
        status="active",
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
    d = {"vm1": vm1}
    assert info.get_vm_id_by_ip(d, "10.0.0.5") == "vm1"
    assert info.get_vm_id_by_ip(d, "10.0.0.6") is None
