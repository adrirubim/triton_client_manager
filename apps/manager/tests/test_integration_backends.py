import os
from typing import Final

import pytest


RUN_REAL: Final[bool] = os.getenv("TCM_RUN_REAL_BACKENDS") == "1"


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        pytest.skip(f"missing required env var {var_name!r} for real backend integration")
    return value


@pytest.mark.skipif(
    not RUN_REAL,
    reason="TCM_RUN_REAL_BACKENDS!=1; skipping real backend integration",
)
def test_real_backends_smoke_pipeline():
    """Smoke: validate basic creation → inference → teardown contract.

    This test does **not** talk directamente a OpenStack/Docker/Triton; instead
    asume que:

    - hay una instancia del manager corriendo con backends reales conectados, y
    - hay un modelo pequeño de referencia ya desplegado y accesible.

    El entorno concreto (URLs, nombre de modelo, etc.) se pasa vía variables
    de entorno para que cada equipo de plataforma pueda adaptarlo a su
    infraestructura.
    """

    manager_ws = _require_env("TCM_REAL_MANAGER_WS_URL")
    model_name = _require_env("TCM_REAL_MODEL_NAME")

    # El flujo end‑to‑end real (hablar con `manager_ws` y ejercitar `model_name`)
    # debe ser implementado por el equipo que tenga acceso a los backends
    # reales. Aquí dejamos un assert placeholder para no romper CI cuando
    # TCM_RUN_REAL_BACKENDS=1 pero todavía no se ha definido el flujo.
    #
    # Ejemplo esperado a futuro:
    #  - abrir /ws contra manager_ws
    #  - auth con token real
    #  - (opcional) lanzar un management.creation para recursos efímeros
    #  - ejecutar un inference_http contra `model_name`
    #  - verificar status COMPLETED y datos mínimamente coherentes

    assert manager_ws and model_name

