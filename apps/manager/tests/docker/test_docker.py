"""
Comprehensive Docker Test Suite
Tests the complete Docker pipeline: config loading, image discovery, container discovery, and lifecycle
"""

import os
import socket
import sys
import time
from dataclasses import dataclass
from typing import Optional

import pytest
import yaml

from classes.docker.creation import DockerCreation
from classes.docker.deletion import DockerDeletion
from classes.docker.info import DockerInfo


def _docker_worker_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if Docker daemon at host:port is reachable."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


# Mock VM class to simulate OpenStack VM structure
@dataclass
class MockVM:
    id: str
    name: str
    address_private: Optional[str]


def load_config():
    """Load configuration from docker.yaml"""
    config_path = os.path.join(os.path.dirname(__file__), "../../config/docker.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def test_1_load_config(config=None):
    """Test 1: Load and validate configuration"""
    print("\n" + "=" * 60)
    print("TEST 1: Load Configuration from docker.yaml")
    print("=" * 60)

    cfg = config if config is not None else load_config()
    assert cfg is not None, "Failed to load configuration"

    print("\n✅ Configuration loaded successfully:")
    print(f"   Registry Endpoint: {cfg['registry_endpoint']}")
    print(f"   Registry Address: {cfg['registry_address']}")
    print(f"   Registry Timeout: {cfg['registry_timeout']}s")
    print(f"   Image Types: {cfg['registry_image_types']}")
    print(f"   Remote API Port: {cfg['remote_api_port']}")
    print(f"   Remote API Timeout: {cfg['remote_api_timeout']}s")
    print(f"   Refresh Time: {cfg['refresh_time']}s")


def test_2_registry_images(config):
    """Test 2: Discover images from Docker registry"""
    print("\n" + "=" * 60)
    print("TEST 2: Discover Images from Registry")
    print("=" * 60)

    docker_info = DockerInfo(config)
    print(f"\n📡 Connecting to registry: {config['registry_endpoint']}")
    images = docker_info.load_images()

    assert images is not None, "Failed to load images from registry"
    print(f"\n✅ SUCCESS: Loaded {len(images)} images")

    if images:
        print("\n📦 Available Images:")
        for key, img in images.items():
            print(f"\n   {key}")
            print(f"      Name: {img.name}")
            print(f"      Tag: {img.tag}")
            if img.digest:
                print(f"      Digest: {img.digest[:20]}...")
            if img.size:
                print(f"      Size: {img.size:,} bytes")
    else:
        print("\n⚠️  No images found in registry")


def test_3_container_discovery(config):
    """Test 3: Discover containers from worker VMs"""
    print("\n" + "=" * 60)
    print("TEST 3: Discover Containers from Worker VMs")
    print("=" * 60)

    docker_info = DockerInfo(config)
    mock_vms = {"vm-001": MockVM(id="vm-001", name="docker-worker-1", address_private="10.0.0.5")}

    print("\n📡 Querying worker VMs...")
    print(f"   Worker: 10.0.0.5:{config['remote_api_port']}")

    containers_by_ip = docker_info.load_containers(mock_vms)
    assert containers_by_ip is not None, "Failed to load containers"

    total_containers = sum(len(c) for c in containers_by_ip.values())
    print(f"\n✅ SUCCESS: Discovered {total_containers} containers")

    for worker_ip, containers in containers_by_ip.items():
        print(f"\n🖥️  Worker: {worker_ip}")
        print(f"   Containers: {len(containers)}")

        for container in containers:
            print(f"\n   📦 {container.name}")
            print(f"      ID: {container.id[:12]}")
            print(f"      Image: {container.image_name}:{container.image_tag}")
            print(f"      Status: {container.status}")
            print(f"      State: {container.state}")
            if container.ports:
                print(f"      Ports: {container.ports}")


def test_4_container_lifecycle(config, mock_vms):
    """Test 4: Create and delete container lifecycle (requires reachable Docker worker)."""
    worker_ip = "10.0.0.5"
    worker_port = config.get("remote_api_port", 2376)
    if not _docker_worker_reachable(worker_ip, worker_port):
        pytest.skip(
            f"Docker worker at {worker_ip}:{worker_port} not reachable " "(run in environment with access to worker VM)"
        )

    print("\n" + "=" * 60)
    print("TEST 4: Container Lifecycle (Create & Delete)")
    print("=" * 60)

    docker_creation = DockerCreation(config)
    docker_deletion = DockerDeletion(config)
    docker_info = DockerInfo(config)

    test_image = "tritonserver:25.12-py3-ARM"
    test_container_name = "test_docker_container"
    container_id = None

    try:
        # Step 1: Create Container
        print("\n" + "-" * 60)
        print("STEP 1: Creating Container")
        print("-" * 60)

        print("\n📦 Creating container...")
        print(f"   Worker: {worker_ip}")
        print(f"   Image: {test_image}")
        print(f"   Name: {test_container_name}")

        container_id = docker_creation.handle(
            worker_ip=worker_ip,
            image=test_image,
            name=test_container_name,
            command=["sleep", "300"],
            detach=True,
            auto_remove=False,
        )

        assert container_id, "Container creation failed"
        print(f"\n✅ Container created: {container_id[:12]}")

        # Step 2: Verify Container Exists
        print("\n" + "-" * 60)
        print("STEP 2: Verifying Container Exists")
        print("-" * 60)

        time.sleep(2)  # Wait for container to start

        containers_by_ip = docker_info.load_containers(mock_vms)

        found = False
        if worker_ip in containers_by_ip:
            for container in containers_by_ip[worker_ip]:
                if container.id == container_id or container.name == test_container_name:
                    found = True
                    print("\n✅ Container verified in list")
                    print(f"   Name: {container.name}")
                    print(f"   Image: {container.image_name}:{container.image_tag}")
                    print(f"   Status: {container.status}")
                    print(f"   State: {container.state}")
                    break

        if not found:
            print("\n⚠️  Container not found in list (may still be starting)")

        # Step 3: Delete Container
        print("\n" + "-" * 60)
        print("STEP 3: Deleting Container")
        print("-" * 60)

        print(f"\n🗑️  Deleting container: {container_id[:12]}")

        success = docker_deletion.handle(
            worker_ip=worker_ip,
            container_id=container_id,
            force=True,
            remove_volumes=False,
        )

        assert success, "Container deletion failed"
        print("\n✅ Container deleted successfully")

        # Step 4: Verify Container is Gone
        print("\n" + "-" * 60)
        print("STEP 4: Verifying Container Removed")
        print("-" * 60)

        time.sleep(2)  # Wait for deletion to complete

        containers_by_ip = docker_info.load_containers(mock_vms)

        still_exists = False
        if worker_ip in containers_by_ip:
            for container in containers_by_ip[worker_ip]:
                if container.id == container_id or container.name == test_container_name:
                    still_exists = True
                    break

        assert not still_exists, "Container still exists after deletion"
        print("\n✅ Container successfully removed")

    except Exception:
        import traceback

        traceback.print_exc()
        if container_id:
            print("\n🧹 Attempting cleanup...")
            try:
                docker_deletion.handle(worker_ip, container_id, force=True)
                print("✓ Cleanup successful")
            except Exception:
                print("✗ Cleanup failed - manual cleanup may be required")
        raise


def main():
    print("=" * 60)
    print("🐳 COMPREHENSIVE DOCKER TEST SUITE")
    print("=" * 60)
    print("\nThis test covers:")
    print("  1. Configuration loading from docker.yaml")
    print("  2. Image discovery from registry")
    print("  3. Container discovery from worker VMs")
    print("  4. Container lifecycle (create & delete)")
    print("=" * 60)

    results = []
    config = None
    mock_vms = {"vm-001": MockVM(id="vm-001", name="docker-worker-1", address_private="10.0.0.5")}

    try:
        config = load_config()
        test_1_load_config(config)
        results.append(("Configuration Loading", True))
    except Exception as e:
        print(f"\n❌ Cannot proceed: {e}")
        results.append(("Configuration Loading", False))
        _print_summary(results)
        return False

    try:
        test_2_registry_images(config)
        results.append(("Registry Image Discovery", True))
    except Exception as e:
        print(f"\n❌ Registry test failed: {e}")
        results.append(("Registry Image Discovery", False))

    try:
        test_3_container_discovery(config)
        results.append(("Container Discovery", True))
    except Exception as e:
        print(f"\n❌ Discovery test failed: {e}")
        results.append(("Container Discovery", False))

    try:
        test_4_container_lifecycle(config, mock_vms)
        results.append(("Container Lifecycle", True))
    except Exception as e:
        print(f"\n❌ Lifecycle test failed: {e}")
        results.append(("Container Lifecycle", False))

    _print_summary(results)
    return all(r[1] for r in results)


def _print_summary(results):
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    print("\n" + "=" * 60)
    print(f"Final Score: {passed}/{total} tests passed")
    if passed == total:
        print("🎉 ALL TESTS PASSED!")
    else:
        print("⚠️  Some tests failed")
    print("=" * 60)


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Test suite failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
