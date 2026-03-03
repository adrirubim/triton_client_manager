from unittest.mock import MagicMock

from classes.triton.deletion.deletion import TritonDeletion


def test_triton_deletion_handle_success_and_failure():
    d = TritonDeletion()

    client_ok = MagicMock()
    assert d.handle(client_ok, "model") is True
    client_ok.unload_model.assert_called_once_with("model")

    client_fail = MagicMock()

    def raise_err(name):
        raise RuntimeError("boom")

    client_fail.unload_model.side_effect = raise_err
    assert d.handle(client_fail, "model") is False
