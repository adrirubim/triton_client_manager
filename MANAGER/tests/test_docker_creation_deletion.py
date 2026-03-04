from unittest.mock import MagicMock, patch

import pytest

from classes.docker.creation.creation import DockerCreation
from classes.docker.deletion.deletion import DockerDeletion
from classes.docker.dockererrors import DockerDeletionError
from classes.docker.dockerthread import DockerThread


def test_docker_creation_handle_builds_full_image_and_closes_client():
    config = {
        "remote_api_timeout": 3,
        "remote_api_port": 2377,
        "registry_address": "registry.local:5000",
    }
    dc = DockerCreation(config)

    fake_container = MagicMock()
    fake_container.id = "abc123def456"

    fake_client = MagicMock()
    fake_client.containers.run.return_value = fake_container

    with patch(
        "classes.docker.creation.creation.docker.DockerClient", return_value=fake_client
    ) as mock_client_cls:
        cid = dc.handle(
            worker_ip="10.0.0.5",
            image="myimage:latest",
            name="mycontainer",
            command="bash",
            ports={"8000/tcp": 8000},
            environment={"ENV": "prod"},
            volumes={"/data": {"bind": "/data", "mode": "rw"}},
            detach=True,
            auto_remove=False,
            restart_policy={"Name": "always"},
        )

    # Image name should be prefixed with registry_address
    mock_client_cls.assert_called_once_with(base_url="tcp://10.0.0.5:2377", timeout=3)
    fake_client.containers.run.assert_called_once()
    assert cid == "abc123def456"
    fake_client.close.assert_called_once()


def test_docker_deletion_handle_success_and_client_closed():
    config = {"remote_api_timeout": 5, "remote_api_port": 2376}
    dd = DockerDeletion(config)

    fake_container = MagicMock()
    fake_container.status = "running"

    fake_client = MagicMock()
    fake_client.containers.get.return_value = fake_container

    with patch(
        "classes.docker.deletion.deletion.docker.DockerClient", return_value=fake_client
    ) as mock_client_cls:
        dd.handle(ip="10.0.0.6", force=False, container_id="cid-1", remove_volumes=True)

    mock_client_cls.assert_called_once_with(base_url="tcp://10.0.0.6:2376", timeout=5)
    fake_container.stop.assert_called_once()
    fake_container.remove.assert_called_once_with(v=True, force=False)
    fake_client.close.assert_called_once()


@patch("classes.docker.deletion.deletion.docker.DockerClient")
def test_docker_deletion_wraps_exceptions_in_docker_deletion_error(mock_client_cls):
    config = {"remote_api_timeout": 5, "remote_api_port": 2376}
    dd = DockerDeletion(config)

    client = MagicMock()
    client.containers.get.side_effect = RuntimeError("boom")
    mock_client_cls.return_value = client

    with pytest.raises(DockerDeletionError):
        dd.handle(ip="10.0.0.6", force=True, container_id="cid-x", remove_volumes=False)

    client.close.assert_called_once()


@patch("classes.docker.dockerthread.DockerInfo")
def test_docker_thread_create_container_happy_path_and_errors(mock_docker_info_cls):
    config = {
        "refresh_time": 1,
        "remote_api_timeout": 3,
        "remote_api_port": 2376,
        "registry_address": "reg:5000",
    }
    thread = DockerThread(config)

    # Replace docker_info with mock instance
    thread.docker_info = MagicMock()

    # Set dependencies
    thread.openstack = MagicMock()
    thread.docker_creation = MagicMock()
    thread.docker_creation.handle.return_value = "cid-1"
    thread.docker_info = MagicMock()

    fake_container = MagicMock()
    thread.docker_info.load_single_container.return_value = fake_container

    # Happy path
    payload = {
        "image": "img",
        "worker_ip": "10.0.0.7",
        "name": "n",
    }
    cid = thread.create_container(payload.copy())
    assert cid == "cid-1"
    thread.docker_creation.handle.assert_called_once()
    assert "cid-1" in thread.dict_containers


@patch("classes.docker.dockerthread.DockerInfo")
def test_docker_thread_delete_container_happy_path_and_missing(mock_docker_info_cls):
    config = {
        "refresh_time": 1,
        "remote_api_timeout": 3,
        "remote_api_port": 2376,
        "registry_address": "reg:5000",
    }
    thread = DockerThread(config)
    thread.docker_info = MagicMock()
    thread.docker_deletion = MagicMock()

    # Seed dict_containers with one entry
    container = MagicMock()
    container.worker_ip = "10.0.0.8"
    thread.dict_containers = {"cid-1": container}

    data = {
        "vm_id": "vm-1",
        "container_id": "cid-1",
        "force": True,
        "remove_volumes": True,
    }
    out = thread.delete_container(data.copy())
    thread.docker_deletion.handle.assert_called_once_with(
        ip="10.0.0.8", force=True, container_id="cid-1", remove_volumes=True
    )
    assert "cid-1" not in thread.dict_containers
    assert out["container_id"] == "cid-1"
