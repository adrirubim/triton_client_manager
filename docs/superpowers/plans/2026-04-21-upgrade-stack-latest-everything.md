# Upgrade “latest everything” Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Subir **todo el stack** (Python deps + imágenes Docker/Compose + manifests K8s) a versiones “latest” (incluyendo majors) y recuperar estado **verde** con `./scripts/dev-verify.sh` tras cada lote.

**Architecture:** Upgrades por capas (lotes) con verificación obligatoria tras cada lote. Si algo falla, se arregla inmediatamente antes de continuar.

**Tech Stack:** Python (pip + requirements/pyproject), FastAPI/Uvicorn, Docker/Compose, Kubernetes manifests, Triton Inference Server, Prometheus, Grafana.

---

## Mapa de archivos a tocar

**Python / deps**
- Modify: `apps/manager/requirements-test.txt`
- Modify: `apps/manager/requirements.txt`
- Modify: `apps/docker_controller/requirements.txt`
- Modify: `apps/manager/openstack_tools/docker-vm/auto-update/requirements.txt`
- Modify (opcional): `apps/manager/requirements-model-tools.txt`
- Modify (si se decide ampliar rangos): `sdk/pyproject.toml`, `apps/manager/pyproject.toml`

**Infra**
- Modify: `Dockerfile.manager`
- Modify: `infra/triton/docker-compose.yml`
- Modify: `infra/monitoring/docker-compose.yml`
- Modify: `infra/monitoring/docker-compose.dev.yml`
- Modify (si aplica): `infra/k8s/*.yaml`
- Modify: `VERSION_STACK.md`

**Quality gate / scripts**
- Modify: `scripts/dev-verify.sh` (solo si la verificación necesita compatibilidad con nuevas herramientas/paths)

---

## Task 0: Baseline + guardrails (antes de cambiar nada)

**Files:**
- Read: `apps/manager/requirements*.txt`
- Read: `Dockerfile.manager`
- Read: `infra/*/*.yml`

- [ ] **Step 1: Asegurar venv activo (repo root)**

Run:
```bash
cd /var/www/triton_client_manager
source .venv/bin/activate
python -V
python -m pip -V
```

Expected: Python 3.x, pip imprime ruta dentro de `.venv`.

- [ ] **Step 2: Capturar snapshot de dependencias instaladas**

Run:
```bash
python -m pip freeze > /tmp/tcm-freeze.baseline.txt
```

Expected: archivo generado sin errores.

- [ ] **Step 3: Confirmar que el quality gate pasa antes del siguiente lote**

Run:
```bash
./scripts/dev-verify.sh
```

Expected: termina con “Quality gate completed successfully.”

---

## Task 1: Lote 1 — Tooling y tests del manager (incl. majors)

**Files:**
- Modify: `apps/manager/requirements-test.txt`
- Modify (si hay que ajustar): `apps/manager/pyproject.toml`
- Verify: `scripts/dev-verify.sh`

- [ ] **Step 1: Identificar qué está desactualizado en tooling/tests**

Run:
```bash
python -m pip index versions websockets
python -m pip index versions coverage
python -m pip index versions ruff
python -m pip index versions black
python -m pip index versions flake8
python -m pip index versions pytest
python -m pip index versions pytest-cov
python -m pip index versions pytest-asyncio
```

Expected: cada comando lista `LATEST` y versiones disponibles.

- [ ] **Step 2: Subir pins de `apps/manager/requirements-test.txt` a latest**

Edit:
- Cambiar estos pins a su `LATEST` mostrado por pip:
  - `coverage==...`
  - `websockets==...`
  - `ruff==...`
  - `black==...`
  - `flake8==...`
  - (si difiere de `requirements.txt`) `pytest==...`, `pytest-cov==...`, `pytest-asyncio==...`

- [ ] **Step 3: Reinstalar deps de test**

Run:
```bash
python -m pip install -r apps/manager/requirements-test.txt
```

Expected: instala/actualiza paquetes y termina sin errores.

- [ ] **Step 4: Ejecutar verificación**

Run:
```bash
./scripts/dev-verify.sh
```

Expected: quality gate completo OK. Si falla, arreglar inmediatamente (config de ruff/black o incompatibilidades).

- [ ] **Step 5: Capturar snapshot post-lote**

Run:
```bash
python -m pip freeze > /tmp/tcm-freeze.lote1-tests.txt
```

---

## Task 2: Lote 2 — Runtime manager core (incl. majors: numpy/protobuf/uvicorn/etc.)

**Files:**
- Modify: `apps/manager/requirements.txt`
- Verify: `scripts/dev-verify.sh`

- [ ] **Step 1: Identificar latest de los paquetes críticos**

Run:
```bash
python -m pip index versions fastapi
python -m pip index versions uvicorn
python -m pip index versions wsproto
python -m pip index versions docker
python -m pip index versions tritonclient
python -m pip index versions numpy
python -m pip index versions protobuf
python -m pip index versions pydantic
python -m pip index versions boto3
python -m pip index versions safetensors
python -m pip index versions PyYAML
python -m pip index versions requests
python -m pip index versions Pillow
python -m pip index versions prometheus-client
python -m pip index versions PyJWT
```

- [ ] **Step 2: Subir pins en `apps/manager/requirements.txt` a latest**

Edit:
- Reemplazar cada `==` por la versión `LATEST` mostrada.

Notas esperadas de cambios major:
- `numpy` probablemente sube a `2.x`
- `protobuf` probablemente sube a `7.x`
- `uvicorn` sube a `0.44.x` (aprox)

- [ ] **Step 3: Reinstalar runtime**

Run:
```bash
python -m pip install -r apps/manager/requirements.txt
```

- [ ] **Step 4: Ejecutar verificación**

Run:
```bash
./scripts/dev-verify.sh
```

Expected: pasa. Si falla:
- Corregir compatibilidades en código (por ejemplo, imports, API changes).
- Repetir `./scripts/dev-verify.sh` hasta verde.

- [ ] **Step 5: Snapshot post-lote**

Run:
```bash
python -m pip freeze > /tmp/tcm-freeze.lote2-runtime.txt
```

---

## Task 3: Lote 3 — Módulos auxiliares (docker_controller + auto-update + model-tools)

**Files:**
- Modify: `apps/docker_controller/requirements.txt`
- Modify: `apps/manager/openstack_tools/docker-vm/auto-update/requirements.txt`
- Modify (opcional): `apps/manager/requirements-model-tools.txt`
- Verify: `scripts/dev-verify.sh`

- [ ] **Step 1: Decidir si “model-tools” entra en ‘latest everything’**

Policy (para este plan): **sí entra**.

- [ ] **Step 2: Subir pins de `apps/docker_controller/requirements.txt` a latest**

Run:
```bash
python -m pip index versions docker
python -m pip index versions PyYAML
python -m pip index versions requests
python -m pip index versions certifi
python -m pip index versions urllib3
python -m pip index versions charset-normalizer
python -m pip index versions idna
```

Edit: actualizar las versiones a `LATEST`.

- [ ] **Step 3: Subir deps auto-update (no fijadas)**

Archivo `apps/manager/openstack_tools/docker-vm/auto-update/requirements.txt` usa deps sin pin.
Acción: fijarlas a latest (para consistencia “latest everything”):
- Cambiar `requests` → `requests==<LATEST>`
- Cambiar `docker` → `docker==<LATEST>`
- Cambiar `pyyaml` → `pyyaml==<LATEST>`

Instalar:
```bash
python -m pip install -r apps/manager/openstack_tools/docker-vm/auto-update/requirements.txt
```

- [ ] **Step 4: Subir `onnx` model-tools**

Run:
```bash
python -m pip index versions onnx
```

Edit: `apps/manager/requirements-model-tools.txt` → `onnx==<LATEST>`

Instalar:
```bash
python -m pip install -r apps/manager/requirements-model-tools.txt
```

- [ ] **Step 5: Verificar**

Run:
```bash
./scripts/dev-verify.sh
```

---

## Task 4: Lote 4 — SDK Python (`sdk/pyproject.toml`)

**Files:**
- Modify: `sdk/pyproject.toml`
- Verify: `scripts/dev-verify.sh`

- [ ] **Step 1: Evaluar dependencias del SDK**

El SDK usa rangos (ej. `websockets>=12,<13`). Para “latest everything”:
- Subir rangos para permitir la última major estable.

- [ ] **Step 2: Ajustar rangos a majors actuales**

Edit `sdk/pyproject.toml`:
- `websockets>=16,<17`
- `numpy>=2.0`
- `pydantic>=2.0` (mantener, ya es v2)
- `onnx>=<LATEST_MAJOR>` (si procede)

- [ ] **Step 3: Verificar**

Run:
```bash
./scripts/dev-verify.sh
```

---

## Task 5: Lote 5 — Docker base image (Python) + build

**Files:**
- Modify: `Dockerfile.manager`
- Verify: build + `./scripts/dev-verify.sh`

- [ ] **Step 1: Subir base image a última minor estable**

Edit `Dockerfile.manager`:
- `FROM python:3.12-slim` → `FROM python:3.13-slim`

- [ ] **Step 2: Build**

Run:
```bash
docker build -f Dockerfile.manager -t tcm-manager:local .
```

Expected: build OK.

- [ ] **Step 3: Verificar**

Run:
```bash
./scripts/dev-verify.sh
```

---

## Task 6: Lote 6 — Infra Compose (Triton + Monitoring)

**Files:**
- Modify: `infra/triton/docker-compose.yml`
- Modify: `infra/monitoring/docker-compose.yml`
- Modify: `infra/monitoring/docker-compose.dev.yml`

- [ ] **Step 1: Triton tag**

Policy (2026-04): latest estable = `nvcr.io/nvidia/tritonserver:26.03-py3`.
Acción:
- Si ya está en `26.03-py3`, no cambiar.
- Si no, actualizar `infra/triton/docker-compose.yml` a `26.03-py3`.

- [ ] **Step 2: Fijar versiones Prometheus/Grafana**

Edit `infra/monitoring/docker-compose.yml`:
- `prom/prometheus:<version>` → `prom/prometheus:v3.10.0`
- `grafana/grafana:<version>` → `grafana/grafana:13.0.1`

- [ ] **Step 3: Validar compose**

Run:
```bash
docker compose -f infra/monitoring/docker-compose.yml config
docker compose -f infra/triton/docker-compose.yml config
```

Expected: config renderiza sin errores.

---

## Task 7: Lote 7 — K8s + docs de versión

**Files:**
- Modify: `VERSION_STACK.md`
- Modify (si aplica): `infra/k8s/*.yaml`

- [ ] **Step 1: Actualizar `VERSION_STACK.md`**

Actualizar tabla con:
- Python recomendado (si subiste a 3.13)
- FastAPI/Uvicorn
- `numpy`, `protobuf`
- Triton image tag (26.03-py3 o el que corresponda)
- Prometheus/Grafana tags

- [ ] **Step 2: Validar manifests**

Run:
```bash
kubectl kustomize infra/k8s 2>/dev/null || true
```

(Si no hay kustomize/cluster, al menos validar YAML no tenga placeholders.)

---

## Self-review del plan (antes de ejecutar)

- Confirmar que cada lote termina con `./scripts/dev-verify.sh`.
- Confirmar que no quedan `<version>` en compose.
- Confirmar que “latest” está concretado en tags/versiones.

---

## Ejecución: elige enfoque

Plan completo y guardado en `docs/superpowers/plans/2026-04-21-upgrade-stack-latest-everything.md`. Dos opciones:

1. **Subagent-Driven (recomendado)** — un subagente por task, revisión entre tasks  
2. **Inline Execution** — ejecutar tasks en esta sesión, con checkpoints frecuentes

¿Cuál prefieres?

