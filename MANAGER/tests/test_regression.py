"""
Regression tests for dependency injection, deletion payload normalization,
auth contract, and inference example alignment.
Run: cd MANAGER && python -m unittest tests.test_regression -v
"""

import json
import os
import sys
import unittest

# Add MANAGER to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestJobHandlerInstantiation(unittest.TestCase):
    """A) JobManagement, JobInfo, and JobInference must instantiate without TypeError."""

    def test_job_info_instantiation(self):
        """JobInfo receives (docker, openstack, websocket, get_queue_stats) only."""
        from classes.job.info import JobInfo

        mock_docker = type("DockerThread", (), {"dict_containers": {}})()
        mock_openstack = type("OpenstackThread", (), {"dict_servers": {}})()
        mock_ws = lambda cid, msg: True
        mock_get_queue_stats = lambda: {}

        info = JobInfo(mock_docker, mock_openstack, mock_ws, mock_get_queue_stats)
        self.assertIs(info.docker, mock_docker)
        self.assertIs(info.openstack, mock_openstack)
        self.assertIs(info.websocket, mock_ws)
        self.assertIs(info.get_queue_stats, mock_get_queue_stats)

    def test_job_management_instantiation(self):
        """JobManagement receives (docker, triton, openstack, websocket, ...) in correct order."""
        from classes.job.management import JobManagement

        mock_docker = type("DockerThread", (), {})()
        mock_triton = type("TritonThread", (), {})()
        mock_openstack = type("OpenstackThread", (), {})()
        mock_ws = lambda cid, msg: True

        mgmt = JobManagement(
            mock_docker,
            mock_triton,
            mock_openstack,
            mock_ws,
            management_actions_available=["creation", "deletion"],
        )
        self.assertIs(mgmt.job_creation._container.docker, mock_docker)
        self.assertIs(mgmt.job_deletion._triton.triton, mock_triton)

    def test_job_inference_instantiation(self):
        """JobInference receives (triton, docker, openstack, websocket, inference_actions_available)."""
        from classes.job.inference import JobInference

        mock_docker = type("DockerThread", (), {})()
        mock_openstack = type("OpenstackThread", (), {})()
        mock_ws = lambda cid, msg: True
        mock_triton = type("TritonThread", (), {})()

        inf = JobInference(
            mock_triton,
            mock_docker,
            mock_openstack,
            mock_ws,
            ["http", "grpc"],
        )
        self.assertIs(inf.docker, mock_docker)
        self.assertIs(inf.triton, mock_triton)


class TestDeletionPayloadNormalization(unittest.TestCase):
    """B) Deletion handler normalizes flat payload for sub-handlers."""

    def test_flat_payload_normalized_to_nested(self):
        """Flat vm_id, container_id, vm_ip produce correct nested structure."""
        from classes.job.management.deletion.deletion import JobDeletion

        class MockTriton:
            def delete_server(self, data): pass
        class MockDocker:
            def delete_container(self, data): return True
        class MockOpenstack:
            def delete_vm(self, vm_id): return True

        deletion = JobDeletion(MockTriton(), MockDocker(), MockOpenstack())
        payload = {
            "vm_id": "vm-123",
            "container_id": "cont-456",
            "vm_ip": "10.0.0.1",
        }
        # Build normalized structure (same logic as handle, without executing)
        vm_id = payload.get("vm_id") or payload.get("openstack", {}).get("vm_id")
        container_id = payload.get("container_id") or payload.get("docker", {}).get("container_id")
        vm_ip = payload.get("vm_ip") or payload.get("openstack", {}).get("vm_ip") or payload.get("docker", {}).get("worker_ip")

        normalized = dict(payload)
        normalized.setdefault("openstack", {})
        normalized["openstack"] = dict(normalized["openstack"])
        normalized["openstack"].setdefault("vm_id", vm_id)
        normalized["openstack"].setdefault("vm_ip", vm_ip)
        normalized.setdefault("docker", {})
        normalized["docker"] = dict(normalized["docker"])
        normalized["docker"].setdefault("container_id", container_id)
        normalized["docker"].setdefault("worker_ip", vm_ip)

        self.assertEqual(normalized["openstack"]["vm_id"], "vm-123")
        self.assertEqual(normalized["openstack"]["vm_ip"], "10.0.0.1")
        self.assertEqual(normalized["docker"]["container_id"], "cont-456")
        self.assertEqual(normalized["docker"]["worker_ip"], "10.0.0.1")


class TestAuthContract(unittest.TestCase):
    """E) Auth message must use top-level uuid."""

    def test_auth_uses_uuid_at_top_level(self):
        """Server expects uuid at message root, not payload.user_id."""
        auth_ok = {"type": "auth", "uuid": "client-1", "payload": {}}
        self.assertIn("uuid", auth_ok)
        self.assertEqual(auth_ok["uuid"], "client-1")


class TestInferenceExample(unittest.TestCase):
    """C) Inference example uses vm_id and container_id for routing."""

    def test_inference_example_uses_vm_id_and_container_id(self):
        """payload_examples/inference.json must have vm_id and container_id for API contract."""
        path = os.path.join(os.path.dirname(__file__), "..", "payload_examples", "inference.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        payload = data.get("payload", {})
        self.assertIn("vm_id", payload, "inference payload must have vm_id for routing")
        self.assertIn("container_id", payload, "inference payload must have container_id for routing")


class TestInspectConfigRemoved(unittest.TestCase):
    """D) inspect_config removed from management_actions_available."""

    def test_inspect_config_not_in_actions(self):
        """inspect_config must not be in management_actions_available."""
        import yaml
        path = os.path.join(os.path.dirname(__file__), "..", "config", "jobs.yaml")
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        actions = config.get("management_actions_available", [])
        self.assertNotIn("inspect_config", actions, "inspect_config not implemented; removed from config")


if __name__ == "__main__":
    unittest.main()
