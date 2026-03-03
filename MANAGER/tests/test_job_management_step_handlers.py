from __future__ import annotations

from dataclasses import dataclass

from classes.job.management.creation.container import JobCreateContainer
from classes.job.management.creation.server import JobCreateServer
from classes.job.management.creation.vm import JobCreateVM
from classes.job.management.deletion.container import JobDeleteContainer
from classes.job.management.deletion.server import JobDeleteServer
from classes.job.management.deletion.vm import JobDeleteVM
from classes.triton.info.data.server import TritonServer


@dataclass
class _FakeOpenstackThread:
    created_payloads: list[dict] = None
    deleted_payloads: list[dict] = None

    def __post_init__(self):
        if self.created_payloads is None:
            self.created_payloads = []
        if self.deleted_payloads is None:
            self.deleted_payloads = []

    def create_vm(self, payload: dict) -> tuple[str, str]:
        self.created_payloads.append(payload)
        return "10.0.0.10", "vm-abc"

    def delete_vm(self, payload: dict) -> None:
        self.deleted_payloads.append(payload)


@dataclass
class _FakeDockerThread:
    created: list[dict] = None
    deleted: list[dict] = None

    def __post_init__(self):
        if self.created is None:
            self.created = []
        if self.deleted is None:
            self.deleted = []

    def create_container(self, payload: dict) -> str:
        self.created.append(payload)
        return "cont-xyz"

    def delete_container(self, payload: dict) -> None:
        self.deleted.append(payload)


@dataclass
class _FakeTritonThread:
    created: list[dict] = None
    deleted: list[dict] = None

    def __post_init__(self):
        if self.created is None:
            self.created = []
        if self.deleted is None:
            self.deleted = []

    def create_server(self, data: dict) -> TritonServer:
        self.created.append(data)
        return TritonServer(
            vm_id=data["vm_id"],
            vm_ip=data["vm_ip"],
            container_id=data["container_id"],
            client=None,  # client not used in these tests
            model_name="demo-model",
            inputs=["inp"],
            outputs=["out"],
        )

    def delete_server(self, payload: dict) -> None:
        self.deleted.append(payload)


def test_job_create_vm_delegates_to_openstack_and_returns_ids():
    openstack = _FakeOpenstackThread()
    step = JobCreateVM(openstack)

    vm_ip, vm_id = step.handle("uuid-vm", {"openstack": {"image_id": "img-1"}})

    assert vm_ip == "10.0.0.10"
    assert vm_id == "vm-abc"
    assert openstack.created_payloads == [{"image_id": "img-1"}]


def test_job_create_container_builds_docker_config_and_sets_defaults():
    docker = _FakeDockerThread()
    step = JobCreateContainer(docker)

    payload = {
        "openstack": {"vm_ip": "10.0.0.10"},
        "docker": {
            "command": ["tritonserver"],
            "ports": {8000: 9000},
        },
        "minio": {
            "endpoint": "http://minio.local:9000",
            "bucket": "models",
            "folder": "resnet",
            "access_key": "AK",
            "secret_key": "SK",
        },
    }

    container_id, docker_config = step.handle("uuid-cont", payload)

    assert container_id == "cont-xyz"
    # worker_ip comes from openstack.vm_ip when vm_ip argument is None
    assert docker_config["worker_ip"] == "10.0.0.10"
    assert docker_config["environment"]["AWS_ACCESS_KEY_ID"] == "AK"
    assert docker_config["environment"]["AWS_SECRET_ACCESS_KEY"] == "SK"
    assert "AWS_DEFAULT_REGION" in docker_config["environment"]
    # ports are normalized using defaults when not provided;
    # in this payload only 8000 is overridden to 9000, so mapping is 9000->8000
    assert docker_config["ports"][9000] == 8000
    assert 8001 in docker_config["ports"].values()
    assert 8002 in docker_config["ports"].values()
    assert docker.created[0] == docker_config


def test_job_create_server_builds_payload_and_uses_triton_thread():
    triton = _FakeTritonThread()
    step = JobCreateServer(triton)

    payload = {
        "openstack": {"vm_id": "vm-1", "vm_ip": "10.0.0.10"},
        "docker": {"container_id": "cont-1"},
        "minio": {},
        "triton": {},
    }

    result = step.handle("uuid-srv", payload)

    assert result["model_name"] == "demo-model"
    assert result["inputs"] == ["inp"]
    assert result["outputs"] == ["out"]
    # TritonThread.create_server must have been called with merged data
    assert len(triton.created) == 1
    called = triton.created[0]
    assert called["vm_id"] == "vm-1"
    assert called["vm_ip"] == "10.0.0.10"
    assert called["container_id"] == "cont-1"


def test_job_delete_steps_delegate_to_underlying_threads():
    docker = _FakeDockerThread()
    triton = _FakeTritonThread()
    openstack = _FakeOpenstackThread()

    del_container = JobDeleteContainer(docker)
    del_server = JobDeleteServer(triton)
    del_vm = JobDeleteVM(openstack)

    payload = {"vm_id": "vm-1", "container_id": "cont-1"}

    assert del_server.handle("uuid-del", payload) == payload
    assert del_container.handle("uuid-del", payload) == payload
    assert del_vm.handle("uuid-del", payload) is None

    assert triton.deleted == [payload]
    assert docker.deleted == [payload]
    assert openstack.deleted_payloads == [payload]

