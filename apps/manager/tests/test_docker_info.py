from unittest.mock import MagicMock

from classes.docker.info.data.container import Container
from classes.docker.info.data.image import Image
from classes.docker.info.info import DockerInfo


def _make_docker_info():
    return DockerInfo(
        {
            "registry_timeout": 1,
            "registry_endpoint": "http://registry.local",
            "registry_image_types": ["tritonserver"],
            "remote_api_timeout": 1,
            "remote_api_port": 2376,
        }
    )


def test_docker_info_load_images_happy_path(monkeypatch):
    info = _make_docker_info()

    class DummyResp:
        def __init__(self, json_data, headers=None, status_ok=True):
            self._json = json_data
            self.headers = headers or {}
            self._ok = status_ok

        def raise_for_status(self):
            if not self._ok:
                raise RuntimeError("bad status")

        def json(self):
            return self._json

    calls = []

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        if url.endswith("/v2/_catalog"):
            return DummyResp({"repositories": ["tritonserver", "other"]})
        if url.endswith("/v2/tritonserver/tags/list"):
            return DummyResp({"tags": ["24.01-py3", "24.02-py3"]})
        if "/v2/tritonserver/manifests/" in url:
            tag = url.rsplit("/", 1)[-1]
            return DummyResp(
                {
                    "config": {
                        "digest": f"sha256:{tag}",
                        "size": 123,
                    }
                },
                headers={"Docker-Content-Digest": f"sha256:{tag}"},
            )
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr("classes.docker.info.info.requests.get", fake_get)
    images = info.load_images()

    assert isinstance(images, dict)
    assert "tritonserver:24.01-py3" in images
    img = images["tritonserver:24.01-py3"]
    assert isinstance(img, Image)
    assert img.digest.startswith("sha256:")


def test_docker_info_load_containers_and_helpers(monkeypatch):
    info = _make_docker_info()

    vm = MagicMock()
    vm.address_private = "10.0.0.5"
    dict_vms = {"vm1": vm}

    class DummyResp:
        def __init__(self, json_data):
            self._json = json_data

        def raise_for_status(self):
            return None

        def json(self):
            return self._json

    def fake_get(url, *args, **kwargs):
        # containers/json or containers/<id>/json
        if url.endswith("/containers/json"):
            return DummyResp(
                [
                    {
                        "Id": "c1",
                        "Names": ["/ctr-1"],
                        "Image": "tritonserver:24.01-py3",
                        "Status": "running",
                        "State": "running",
                        "Ports": [],
                        "Created": 1,
                        "StartedAt": 2,
                    }
                ]
            )
        if "/containers/c1/json" in url:
            return DummyResp(
                {
                    "Id": "c1",
                    "Names": ["/ctr-1"],
                    "Image": "tritonserver:24.01-py3",
                    "Status": "running",
                    "State": "running",
                    "Ports": [],
                    "Created": 1,
                    "StartedAt": 2,
                    "NetworkSettings": {
                        "Ports": {
                            "8000/tcp": [{"HostPort": "18000"}],
                            "9000/tcp": None,
                        }
                    },
                }
            )
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr("classes.docker.info.info.requests.get", fake_get)

    containers = info.load_containers(dict_vms)
    assert "c1" in containers
    c = containers["c1"]
    assert isinstance(c, Container)
    assert c.worker_ip == "10.0.0.5"

    ports = info.get_container_ports("10.0.0.5", "c1")
    assert ports[8000] == 18000
    assert 9000 not in ports  # sin mapeo

    single = info.load_single_container("10.0.0.5", "c1")
    assert isinstance(single, Container)
    assert single.id == "c1"
