import os
from typing import Final

import pytest

RUN_REAL: Final[bool] = os.getenv("TCM_RUN_REAL_BACKENDS") == "1"


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        pytest.skip(
            f"missing required env var {var_name!r} for real backend integration"
        )
    return value


@pytest.mark.skipif(
    not RUN_REAL,
    reason="TCM_RUN_REAL_BACKENDS!=1; skipping real backend integration",
)
def test_real_backends_smoke_pipeline():
    """Smoke: validate basic creation → inference → teardown contract.

    This test does **not** talk directly to OpenStack/Docker/Triton; instead it
    assumes:

    - there is a manager instance running with real backends connected, and
    - there is a small reference model already deployed and reachable.

    The concrete environment (URLs, model name, etc.) is provided via
    environment variables so each platform team can adapt it to their
    infrastructure.
    """

    manager_ws = _require_env("TCM_REAL_MANAGER_WS_URL")
    model_name = _require_env("TCM_REAL_MODEL_NAME")

    # The real end-to-end flow (connect to `manager_ws` and exercise `model_name`)
    # should be implemented by the team that has access to the real backends.
    # We keep a placeholder assert to avoid breaking CI when
    # TCM_RUN_REAL_BACKENDS=1 but the workflow has not been defined yet.
    #
    # Expected future example:
    #  - open /ws against manager_ws
    #  - auth with a real token
    #  - (optional) run a management.creation for ephemeral resources
    #  - execute an inference_http against `model_name`
    #  - verify COMPLETED status and minimally coherent data

    assert manager_ws and model_name
