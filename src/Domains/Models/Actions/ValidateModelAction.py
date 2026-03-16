from __future__ import annotations

import asyncio
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, List, Optional, Tuple

import numpy as np
import requests

from sdk.src.tcm_client.sdk import AuthContext, InferenceInput, TcmClient


TRITON_BASE_URL: Final[str] = "http://localhost:8000"
TRITON_READY_URL: Final[str] = f"{TRITON_BASE_URL}/v2/health/ready"
TRITON_MODEL_METADATA_URL_TEMPLATE: Final[str] = (
    TRITON_BASE_URL + "/v2/models/{model_name}"
)
TRITON_READY_TIMEOUT_SECONDS: Final[int] = 60
TRITON_READY_POLL_INTERVAL_SECONDS: Final[float] = 1.0


@dataclass
class ValidateModelAction:
    """Spin up an ephemeral Triton and validate a real inference via the manager."""

    repo_root: str
    model_name: str
    vm_id: str
    container_id: str
    ws_uri: str = "ws://127.0.0.1:8000/ws"

    def _docker_compose_triton_up(self) -> None:
        compose_file = Path(self.repo_root) / "infra" / "triton" / "docker-compose.yml"
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            check=True,
        )

    def _docker_compose_triton_down(self) -> None:
        compose_file = Path(self.repo_root) / "infra" / "triton" / "docker-compose.yml"
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "down"],
            check=False,
        )

    def _wait_for_triton(self) -> bool:
        """Actively wait until Triton returns 200 on the health endpoint."""
        deadline = time.time() + TRITON_READY_TIMEOUT_SECONDS
        while time.time() < deadline:
            try:
                resp = requests.get(TRITON_READY_URL, timeout=2)
                if resp.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(TRITON_READY_POLL_INTERVAL_SECONDS)
        return False

    def _fetch_model_metadata(self) -> Tuple[List[int], str]:
        """Fetch model metadata from Triton (shape and dtype of the first output)."""
        url = TRITON_MODEL_METADATA_URL_TEMPLATE.format(model_name=self.model_name)
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Triton metadata endpoint returned {resp.status_code} for {url!r}: {resp.text}"
            )

        data = resp.json()
        outputs = data.get("outputs") or []
        if not outputs:
            raise RuntimeError(
                f"Triton metadata for model {self.model_name!r} does not contain outputs."
            )

        first = outputs[0]
        shape = first.get("shape") or first.get("dims")
        dtype = first.get("datatype") or first.get("data_type")
        if not isinstance(shape, list) or not dtype:
            raise RuntimeError(
                f"Incomplete Triton metadata for model {self.model_name!r}: {first!r}"
            )
        return [int(x) for x in shape], str(dtype)

    def _build_dummy_input(self, output_shape: List[int], output_dtype: str) -> InferenceInput:
        """
        Build a dummy input tensor from the model metadata.

        For now we assume a single input with the same shape as the first
        output and FP32 dtype.
        """
        if not output_shape:
            flat_len = 1
            shape = [1]
        else:
            flat_len = int(np.prod(output_shape))
            shape = output_shape

        data = np.zeros(flat_len, dtype=np.float32).tolist()
        return InferenceInput(
            name="INPUT__0",
            shape=shape,
            datatype="FP32",
            data=data,
        )

    async def _validate_inference(self) -> None:
        """Run a real inference via the manager and compare with Triton metadata."""
        meta_shape, meta_dtype = self._fetch_model_metadata()

        ctx = AuthContext(
            uuid="tcm-model-validate",
            token="dummy-token",
            sub="validator",
            tenant_id="validator-tenant",
            roles=["inference"],
        )
        client = TcmClient(self.ws_uri, ctx)

        dummy_input = self._build_dummy_input(meta_shape, meta_dtype)
        response = client.infer(
            vm_id=self.vm_id,
            container_id=self.container_id,
            model_name=self.model_name,
            inputs=[dummy_input],
        )

        if response.type != "inference_response":
            raise RuntimeError(
                f"Unexpected response type from manager: {response.type!r}"
            )

        payload = response.payload or {}
        outputs = payload.get("outputs") or []
        if not outputs:
            raise RuntimeError(
                "Inference response does not contain outputs under `payload.outputs`."
            )

        first = outputs[0]
        out_shape = first.get("shape") or first.get("dims")
        out_dtype = first.get("datatype") or first.get("data_type")

        if not isinstance(out_shape, list) or not out_dtype:
            raise RuntimeError(
                f"Inference output without valid shape or dtype: {first!r}"
            )

        out_shape_list = [int(x) for x in out_shape]
        out_dtype_str = str(out_dtype)

        if out_shape_list != meta_shape or out_dtype_str != meta_dtype:
            raise RuntimeError(
                "Manager inference output does not match Triton metadata:\n"
                f"  Expected (shape, dtype): ({meta_shape}, {meta_dtype})\n"
                f"  Received (shape, dtype): ({out_shape_list}, {out_dtype_str})"
            )

    def run(self) -> None:
        try:
            self._docker_compose_triton_up()

            if not self._wait_for_triton():
                print(
                    "❌ Triton did not respond on "
                    f"{TRITON_READY_URL} within the timeout "
                    f"({TRITON_READY_TIMEOUT_SECONDS}s). "
                    "Check logs for container `tcm-triton-ephemeral`."
                )
                return

            try:
                asyncio.run(self._validate_inference())
                print(
                    f"✅ Inference validation for model '{self.model_name}' "
                    "completed with matching shape and dtype."
                )
            except Exception as exc:
                print(
                    "❌ Model inference validation failed.\n"
                    f"Details: {exc}\n"
                    "Check the model configuration in Triton and routing by "
                    "vm_id/container_id in the manager."
                )
        finally:
            self._docker_compose_triton_down()

