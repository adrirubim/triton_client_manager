# Diseño: Upgrade del stack a “latest everything” (incluyendo majors)

Fecha: 2026-04-21  
Repo: `triton_client_manager`  
Objetivo: **subir todo el stack y dependencias a lo más nuevo disponible, incluyendo upgrades major**, y dejar el repo nuevamente en estado **verde** según el “quality gate” local (`./scripts/dev-verify.sh`), aceptando cambios de código cuando sea necesario.

> Nota: este workspace no está inicializado como repositorio git (no hay commits). El proceso está descrito como si se trabajara en commits por lote, pero aquí quedará como cambios incrementales verificables.

## Alcance (“todo el stack”)

### Python (monorepo)
- **Manager runtime (pins)**: `apps/manager/requirements.txt`
- **Manager dev/test pins**: `apps/manager/requirements-test.txt`
- **Model tooling (opcional)**: `apps/manager/requirements-model-tools.txt`
- **Docker controller**: `apps/docker_controller/requirements.txt`
- **OpenStack tools auto-update**: `apps/manager/openstack_tools/docker-vm/auto-update/requirements.txt`
- **SDK Python**: `sdk/pyproject.toml` (dependencias con rangos)
- **CLI packaging**: `apps/manager/pyproject.toml` (mínimo `pyyaml`)

### Contenedores / imágenes
- **Manager image base**: `Dockerfile.manager` (`python:3.12-slim` → “latest”, previsiblemente `python:3.13-slim`)
- **Triton**: `infra/triton/docker-compose.yml` (`nvcr.io/nvidia/tritonserver:26.03-py3` → último tag estable)
- **Compose demo**: `docker-compose.multi-node.yml` (nginx `alpine` se mantiene “latest”; el manager se publica en GHCR, pero localmente se valida con `Dockerfile.manager`)
- **Observabilidad**: `infra/monitoring/docker-compose.yml` / `infra/monitoring/docker-compose.dev.yml` (Prometheus/Grafana pasan de `<version>` a versiones reales “latest”)

### Kubernetes
- Manifests: `infra/k8s/*.yaml` (principalmente imagen del manager `ghcr.io/...:${TCM_IMAGE_TAG}`)

### Documentación de versiones
- `VERSION_STACK.md` se actualiza para reflejar los cambios reales en runtime + imágenes.

## Definición de “éxito”

- **Quality gate**: `./scripts/dev-verify.sh` termina con “Quality gate completed successfully.”
- **Tests**: no se aceptan regresiones (más allá de skips existentes).
- **Arranque smoke**: la fase “Smoke runtime (with ws client)” sigue funcionando.
- **Infra coherente**: compose/manifest apuntan a tags válidos y reproducibles (no `<version>`).

## Política “latest” (para evitar ambigüedad)

“Latest” no siempre significa usar el tag literal `latest` (especialmente en base images e infra). Para este trabajo:

- **Python deps**: “latest” = **la última versión publicada en PyPI** compatible con el intérprete objetivo del lote.
- **Docker base image (`python:*`)**:
  - “latest” = **la última minor estable** (p. ej. `python:3.13-slim`), no `python:latest`.
  - Si esto obliga a cambios grandes (wheels/compilación), se resuelve en el Lote 5.
- **Triton**: “latest” = **el último tag estable publicado por NVIDIA** con sufijo `-py3` (se elige un tag concreto, no `latest`).
- **Prometheus/Grafana**: “latest” = **la última versión estable** (se fija la versión, no `<version>` ni `latest`).

## Riesgos (por qué esto rompe)

Subir “a latest” con majors típicamente rompe en:
- **`numpy 1.x → 2.x`**: cambios en APIs/ABI, dependencias de terceros.
- **`protobuf 6 → 7`**: cambios de generación/compatibilidad.
- **`websockets 12 → 16`**: cambios de API y compatibilidad con Python/asyncio.
- **`uvicorn 0.30 → 0.44`**: cambios en opciones, dependencias, compatibilidad con FastAPI/Starlette.
- **`pydantic`**: compat con FastAPI/Starlette.
- **Tooling**: `ruff`, `black`, `pytest`, etc. pueden requerir ajustes de configuración.
- **Base image Python**: `python:3.12-slim → python:3.13-slim` puede exigir wheels nuevos o compilación.

## Enfoque recomendado: upgrades por capas (lotes) con verificación

Motivo: maximiza la capacidad de aislar roturas y evita que “todo rompa a la vez”.

### Guardrails (obligatorios)
- Tras **cada lote**, ejecutar `./scripts/dev-verify.sh`.
- Si falla, **no se continúa** con el siguiente lote hasta arreglarlo.
- Cada lote debe ser lo bastante pequeño para poder revertirse mentalmente (idealmente 5–15 paquetes o 1 área de infra).

### Orden de ejecución (lotes)

#### Lote 0 — Baseline / estado actual
- Capturar snapshot de versiones antes (para diagnóstico):
  - `python -m pip freeze` (al menos de manager venv)
  - Tags actuales en compose/k8s

#### Lote 1 — Tooling y tests (manager)
Archivos:
- `apps/manager/requirements-test.txt`
- (posible) config de lint/format en `apps/manager/pyproject.toml`

Objetivo:
- Subir `pytest`, `coverage`, `websockets`, `ruff`, `black`, `flake8`, etc. a latest.
- Ajustar configs/código si cambian reglas o comportamiento.

Verificación:
- `./scripts/dev-verify.sh`

#### Lote 2 — Runtime manager “core”
Archivo:
- `apps/manager/requirements.txt`

Objetivo:
- Subir majors (incl. `uvicorn`, `wsproto`, `docker`, `tritonclient`, `numpy`, `protobuf`, `pydantic`, `boto3`, etc.) a latest.
- Corregir incompatibilidades en runtime.

Verificación:
- `./scripts/dev-verify.sh`

#### Lote 3 — Módulos auxiliares
Archivos:
- `apps/docker_controller/requirements.txt`
- `apps/manager/openstack_tools/docker-vm/auto-update/requirements.txt`
- `apps/manager/requirements-model-tools.txt` (si se considera parte del “todo”)

Objetivo:
- Subir a latest y asegurar que no rompe tests/packaging.

Verificación:
- `./scripts/dev-verify.sh` + (si aplica) checks mínimos por módulo.

#### Lote 4 — SDK Python
Archivo:
- `sdk/pyproject.toml`

Objetivo:
- Subir rangos (o fijar) a latest y validar que el SDK sigue pasando contract tests (ya incluidos en `apps/manager/tests/`).

Verificación:
- `./scripts/dev-verify.sh`

#### Lote 5 — Docker base image + build
Archivo:
- `Dockerfile.manager`

Objetivo:
- Subir base image a latest (p.ej. `python:3.13-slim`) y garantizar build limpio.
- Ajustar librerías del sistema si cambian necesidades (Pillow/crypto/wheels).

Verificación:
- `docker build -f Dockerfile.manager .` + `./scripts/dev-verify.sh`

#### Lote 6 — Compose / infra
Archivos:
- `infra/triton/docker-compose.yml`
- `infra/monitoring/docker-compose.yml`
- `infra/monitoring/docker-compose.dev.yml`

Objetivo:
- Triton: actualizar tag a latest estable.
- Monitoring: sustituir `<version>` por versiones reales y actuales (Prometheus/Grafana).

Verificación:
- `docker compose config` (para validar)
- Arranque local de los stacks (si procede) o, mínimo, validar sintaxis y tags.

#### Lote 7 — K8s manifests + docs
Archivos:
- `infra/k8s/*.yaml`
- `VERSION_STACK.md` (y cualquier doc relevante)

Objetivo:
- Confirmar que variables y tags siguen siendo válidos.
- Actualizar documentación de stack.

## Estrategia de rollback

Sin git, rollback es manual (revertir archivos). Con git, cada lote sería un commit y revert sería trivial.
En cualquier caso:
- Mantener lotes pequeños.
- Mantener un snapshot de `pip freeze` por lote.

## Plan de verificación

Fuente de verdad:
- `./scripts/dev-verify.sh`

Además, para “latest everything”:
- `python -m pip list --outdated` se usa como *señal*, no como criterio final (puede incluir paquetes no fijados).

### Comprobación “outdated” enfocada a lo fijado

Como `pip list --outdated` enseña todo lo instalado, el criterio de “subido a latest” se aplica a:
- lo que esté **fijado** en `requirements*.txt` (pins `==`), y
- las dependencias declaradas en `pyproject.toml` (rangos), cuando se decida ampliarlas/ajustarlas.


