from __future__ import annotations

import asyncio

from tcm_client.sdk import AuthContext, InferenceInput, TcmClient


def test_tcmclient_infer_raises_inside_running_event_loop() -> None:
    ctx = AuthContext(
        uuid="test-client",
        token="dummy-token",
        sub="user",
        tenant_id="tenant",
        roles=["inference"],
    )
    client = TcmClient("ws://127.0.0.1:8000/ws", ctx)

    async def _inner() -> None:
        try:
            client.infer(
                vm_id="vm-1",
                container_id="ctr-1",
                model_name="model",
                inputs=[
                    InferenceInput(
                        name="INPUT__0",
                        shape=[1],
                        datatype="FP32",
                        data=[0.0],
                    )
                ],
            )
        except RuntimeError as e:
            assert "infer_async" in str(e)
        else:
            raise AssertionError("Expected RuntimeError inside running event loop")

    asyncio.run(_inner())
