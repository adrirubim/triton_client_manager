from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, List, Optional, Tuple

import numpy as np
import requests

from sdk.src.tcm_client.sdk import AuthContext, InferenceInput, TcmClient

# Triton is exposed on host port 8001 by infra/triton/docker-compose.yml.
TRITON_BASE_URL: Final[str] = "http://localhost:8001"
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
    vm_ip: Optional[str] = None
    ws_uri: str = "ws://127.0.0.1:8000/ws"

    def _resolve_local_container_id(self) -> str:
        """
        In local dev, ValidateModelAction starts Triton via docker compose.
        The container ID changes every time, so we resolve it from the known
        container name instead of relying on user-provided IDs.
        """
        try:
            out = subprocess.check_output(
                ["docker", "ps", "-q", "--filter", "name=tcm-triton-ephemeral"],
                text=True,
            ).strip()
        except Exception:
            out = ""

        if not out:
            raise RuntimeError(
                "Could not resolve local Triton container id for 'tcm-triton-ephemeral'. "
                "Is docker running and did compose start the container?"
            )
        return out

    def _resolve_local_container_ip(self) -> str:
        """
        Resolve the container IP address on the docker network.

        The manager expects to talk to Triton on the *container* ports
        (HTTP 8000 / gRPC 8001), not the host-published ports.
        """
        try:
            out = subprocess.check_output(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                    "tcm-triton-ephemeral",
                ],
                text=True,
            ).strip()
        except Exception:
            out = ""

        if not out:
            raise RuntimeError(
                "Could not resolve local Triton container IP for 'tcm-triton-ephemeral'."
            )
        return out

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

    def _build_dummy_input(
        self, output_shape: List[int], output_dtype: str
    ) -> InferenceInput:
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

    def _validate_inference(self) -> None:
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
            vm_ip=self.vm_ip,
            container_id=self.container_id,
            model_name=self.model_name,
            inputs=[dummy_input],
            allow_transient=True,
        )

        # The manager historically responded with `inference_response`, but the
        # runtime job pipeline also emits `type="inference"` with a `status`
        # envelope. Accept both for local dev.
        if response.type not in {"inference_response", "inference"}:
            raise RuntimeError(
                "Unexpected response type from manager "
                f"(type={response.type!r}, payload={response.payload!r})"
            )

        payload = response.payload or {}

        if response.type == "inference":
            status = payload.get("status")
            if status != "COMPLETED":
                raise RuntimeError(
                    f"Inference did not complete successfully (status={status!r}, payload={payload!r})"
                )

            data = payload.get("data")
            if not isinstance(data, dict) or not data:
                raise RuntimeError(
                    f"Inference completed but no outputs were returned (payload={payload!r})"
                )

            # Best-effort validation: ensure we got at least one output tensor and
            # its flattened length matches Triton's metadata.
            expected_len = int(np.prod(meta_shape)) if meta_shape else 1
            first_value = next(iter(data.values()))
            if isinstance(first_value, list) and len(first_value) != expected_len:
                raise RuntimeError(
                    "Manager inference output length does not match Triton metadata:\n"
                    f"  Expected flat length: {expected_len}\n"
                    f"  Received: {len(first_value)}"
                )
            return

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
            # Always use the actual local container ID for routing.
            self.container_id = self._resolve_local_container_id()
            # In local dev, route to the container IP so the manager hits the
            # correct Triton ports (8000/8001) instead of host-published 8001.
            self.vm_ip = self._resolve_local_container_ip()

            if not self._wait_for_triton():
                print(
                    "❌ Triton did not respond on "
                    f"{TRITON_READY_URL} within the timeout "
                    f"({TRITON_READY_TIMEOUT_SECONDS}s). "
                    "Check logs for container `tcm-triton-ephemeral`."
                )
                return

            try:
                self._validate_inference()
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
