from __future__ import annotations

from unittest.mock import MagicMock

from classes.triton.info.data.server import TritonServer


def test_triton_server_has_changed_reports_differences():
    client = MagicMock()
    base = TritonServer(
        vm_id="vm1",
        vm_ip="10.0.0.1",
        container_id="c1",
        client=client,
        model_name="m1",
        inputs=["in1"],
        outputs=["out1"],
        status="ready",
    )
    other = TritonServer(
        vm_id="vm1",
        vm_ip="10.0.0.1",
        container_id="c1",
        client=client,
        model_name="m2",
        inputs=["in1", "in2"],
        outputs=["out1"],
        status="busy",
    )

    changed, fields = base.has_changed(other)
    assert changed is True
    # Order is not strictly guaranteed, but all keys must be present.
    assert any("status:" in f for f in fields)
    assert "model_name" in fields
    assert "inputs" in fields
    assert "outputs" not in fields


def test_triton_server_close_swallows_client_errors():
    client = MagicMock()
    client.close.side_effect = RuntimeError("boom")
    server = TritonServer(
        vm_id="vm1",
        vm_ip="10.0.0.1",
        container_id="c1",
        client=client,
    )
    # Should not raise despite client.close failing
    server.close()

