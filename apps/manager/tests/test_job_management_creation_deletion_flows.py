from __future__ import annotations

from dataclasses import dataclass

import pytest

from classes.job.joberrors import JobDeletionFailed, JobDeletionMissingField
from classes.job.management.creation.creation import JobCreation
from classes.job.management.deletion.deletion import JobDeletion


@dataclass
class _DummyVM:
    vm_ip: str = "10.0.0.1"
    vm_id: str = "vm-123"
    deleted: list[str] = None

    def __post_init__(self):
        if self.deleted is None:
            self.deleted = []

    def handle(self, msg_uuid: str, payload: dict) -> tuple[str, str]:
        return self.vm_ip, self.vm_id

    class Openstack:
        def __init__(self, deleted):
            self._deleted = deleted

        def delete_vm(self, vm_id: str) -> None:
            self._deleted.append(vm_id)

    @property
    def openstack(self):
        return _DummyVM.Openstack(self.deleted)


@dataclass
class _DummyContainer:
    container_id: str = "cont-456"
    deleted: list[dict] = None
    should_fail: bool = False

    def __post_init__(self):
        if self.deleted is None:
            self.deleted = []

    def handle(self, msg_uuid: str, payload: dict, vm_ip: str | None = None):
        if self.should_fail:
            raise RuntimeError("container failure")
        return self.container_id, {"vm_ip": vm_ip}

    class Docker:
        def __init__(self, deleted):
            self._deleted = deleted

        def delete_container(self, payload: dict) -> None:
            self._deleted.append(payload)

    @property
    def docker(self):
        return _DummyContainer.Docker(self.deleted)


@dataclass
class _DummyTritonCreate:
    result: dict
    should_fail: bool = False
    calls: list[tuple] = None

    def __post_init__(self):
        if self.calls is None:
            self.calls = []

    def handle(self, msg_uuid: str, payload: dict, **kwargs) -> dict:
        self.calls.append((msg_uuid, kwargs))
        if self.should_fail:
            raise RuntimeError("triton failure")
        return self.result


@dataclass
class _DummyDeleteStep:
    name: str
    should_fail: bool = False
    calls: list[tuple[str, dict]] = None

    def __post_init__(self):
        if self.calls is None:
            self.calls = []

    def handle(self, msg_uuid: str, payload: dict) -> None:
        self.calls.append((msg_uuid, payload))
        if self.should_fail:
            raise RuntimeError(f"{self.name} failed")


def test_job_creation_happy_path_executes_all_steps_and_returns_payload():
    """Full JobCreation pipeline: VM + container + Triton server."""
    creation = JobCreation(triton=None, docker=None, openstack=None)  # dependencies are patched below

    vm_step = _DummyVM()
    container_step = _DummyContainer()
    triton_step = _DummyTritonCreate(result={"extra": "value"})

    creation._vm = vm_step
    creation._container = container_step
    creation._triton = triton_step

    result = creation.handle("uuid-1", {"openstack": {}, "docker": {}, "minio": {}})

    assert result["vm_ip"] == vm_step.vm_ip
    assert result["container_id"] == container_step.container_id
    assert result["extra"] == "value"
    assert vm_step.deleted == []  # no rollback
    assert container_step.deleted == []  # no container cleanup


def test_job_creation_rolls_back_vm_when_container_creation_fails():
    """If container creation fails, JobCreation must delete the VM."""
    creation = JobCreation(triton=None, docker=None, openstack=None)

    vm_step = _DummyVM()
    container_step = _DummyContainer(should_fail=True)
    creation._vm = vm_step
    creation._container = container_step
    creation._triton = _DummyTritonCreate(result={"extra": "unused"})

    with pytest.raises(RuntimeError, match="container failure"):
        creation.handle("uuid-2", {"openstack": {}, "docker": {}, "minio": {}})

    # VM must be deleted as part of rollback
    assert vm_step.deleted == [vm_step.vm_id]


def test_job_creation_rolls_back_both_container_and_vm_when_triton_fails():
    """If Triton step fails, JobCreation must delete container and VM."""
    creation = JobCreation(triton=None, docker=None, openstack=None)

    vm_step = _DummyVM()
    container_step = _DummyContainer()
    triton_step = _DummyTritonCreate(result={}, should_fail=True)

    creation._vm = vm_step
    creation._container = container_step
    creation._triton = triton_step

    with pytest.raises(RuntimeError, match="triton failure"):
        creation.handle("uuid-3", {"openstack": {}, "docker": {}, "minio": {}})

    # VM rollback
    assert vm_step.deleted == [vm_step.vm_id]
    # Container deletion via Docker
    assert len(container_step.deleted) == 1
    assert container_step.deleted[0]["container_id"] == container_step.container_id
    assert container_step.deleted[0]["force"] is True


def test_job_deletion_missing_fields_raises_job_deletion_missing_field():
    deletion = JobDeletion(triton=None, docker=None, openstack=None)

    with pytest.raises(JobDeletionMissingField):
        deletion.handle("uuid-x", {"container_id": "cont-1"})

    with pytest.raises(JobDeletionMissingField):
        deletion.handle("uuid-x", {"vm_id": "vm-1"})


def test_job_deletion_collects_errors_and_raises_job_deletion_failed():
    deletion = JobDeletion(triton=None, docker=None, openstack=None)

    triton_step = _DummyDeleteStep("triton", should_fail=True)
    container_step = _DummyDeleteStep("container", should_fail=True)
    vm_step = _DummyDeleteStep("vm", should_fail=True)

    deletion._triton = triton_step
    deletion._container = container_step
    deletion._vm = vm_step

    payload = {"vm_id": "vm-1", "container_id": "cont-1"}

    with pytest.raises(JobDeletionFailed) as exc:
        deletion.handle("uuid-del", payload)

    message = str(exc.value)
    assert "triton_delete_server" in message
    assert "delete_container" in message
    assert "delete_vm" in message

    # All delete steps must have been attempted despite failures
    assert len(triton_step.calls) == 1
    assert len(container_step.calls) == 1
    assert len(vm_step.calls) == 1
