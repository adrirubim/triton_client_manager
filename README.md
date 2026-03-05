# Triton Client Manager

> A modern, production-ready orchestrator for OpenStack VMs, Docker containers, and NVIDIA Triton Inference Server. Built with Python 3.12, FastAPI, and uvicorn. Features WebSocket-based job routing, per-user queues, and HTTP/gRPC inference endpoints for AI workloads.

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Uvicorn](https://img.shields.io/badge/Uvicorn-0.30-499848?style=flat)](https://www.uvicorn.org/)
[![Docker](https://img.shields.io/badge/Docker-24+-2496ED?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)
[![Triton Client](https://img.shields.io/badge/Triton_Client-2.65-76B900?style=flat)](https://github.com/triton-inference-server/client)
[![Tests](https://img.shields.io/badge/Tests-smoke%20%2B%20regression-brightgreen?style=flat)](docs/TESTING.md)
[![CI - Tests](https://github.com/adrirubim/triton_client_manager/actions/workflows/tests.yml/badge.svg)](https://github.com/adrirubim/triton_client_manager/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat)](LICENSE)

## 📋 Table of Contents

- [Operational Quickstart](#operational-quickstart)
- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Requirements](#requirements)
- [Installation](#installation)
- [Security](#security)
- [Documentation](#documentation)
- [CI/CD](#cicd)
- [Testing](#testing)
- [Architecture](#architecture)
- [Release Status](#release-status)
- [Default Users](#default-users-development)
- [Useful Commands](#useful-commands)
- [Before Pushing to GitHub](#before-pushing-to-github)
- [Contributing](#contributing)
- [Author](#author)
- [License](#license)

---

<a id="operational-quickstart"></a>
## ⚙️ Operational Quickstart

Use these `make` targets from the **repository root** as the single source of entry for running, validating, and deploying Triton Client Manager:

| Command           | Purpose                                                           | Notes                                                                                 |
| ----------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `make test`       | **Full validation** (pytest + smoke + SDK contract tests)        | Runs the full Python test suite under `MANAGER/`, including WebSocket SDK contracts. |
| `make demo`       | **Multi-replica scaling demo with NGINX**                        | Starts `docker-compose.multi-node.yml` (two manager replicas behind an NGINX LB).     |
| `make monitor`    | **SRE observability stack (Prometheus/Grafana)**                 | Brings up the monitoring stack in `monitoring/docker-compose.yml`.                   |
| `make k8s-deploy` | **Production-style Kubernetes deployment (Deployment + HPA etc.)** | Applies manifests from `k8s/` and prepares the cluster for autoscaling validation.   |

These commands are designed so that any **developer or SRE** can get from clone to:

- A validated runtime (`make test`),
- A horizontal-scaling demo (`make demo`),
- A full observability stack (`make monitor`),
- And a Kubernetes deployment with HPA (`make k8s-deploy`)

with **one command per scenario**.

For deeper operational details and configuration options, see:

- **Runbook:** [docs/RUNBOOK.md](docs/RUNBOOK.md)
- **Configuration reference:** [docs/CONFIGURATION.md](docs/CONFIGURATION.md)

### Operational entrypoints diagram

```mermaid
graph TD
    User(["Developer / SRE"]) -->|make test| CI["Full Validation (CI-equivalent)"]
    User -->|make demo| MultiNode["Local Multi-Replica Scaling (NGINX)"]
    User -->|make monitor| Obs["Observability Stack (Prometheus & Grafana)"]
    User -->|make k8s-deploy| K8s["Production-style Kubernetes Cluster"]
    
    subgraph "Triton Client Manager v1.0.0"
        CI -.-> SDK["Python SDK Contract Tests"]
        MultiNode --> Manager1["Manager Replica 1"]
        MultiNode --> Manager2["Manager Replica 2"]
        Obs --> Metrics["Metrics Endpoint (/metrics)"]
        K8s --> HPA["Horizontal Pod Autoscaler"]
    end
```

---

<a id="overview"></a>
## 🎯 Overview

Triton Client Manager is a **control plane** for AI inference pipelines.  
It receives WebSocket messages from an upstream backend, routes them by type (`info`, `management`, `inference`), and coordinates:

- OpenStack VM creation/deletion
- Docker container lifecycle on those VMs
- NVIDIA Triton Inference Server deployment and health checks

The system exposes inference endpoints (HTTP and gRPC) and manages per-user job queues to ensure fair scheduling and isolation.

### Key Highlights

- **Modern stack:** Python 3.12, FastAPI, uvicorn, PyYAML, Triton client
- **OpenStack integration:** VM lifecycle, application credentials, region-aware service catalog
- **Docker integration:** Container management for Triton workers
- **Triton integration:** HTTP/gRPC inference, health checks, routing by `vm_id` / `container_id`
- **WebSockets:** Authenticated clients, per-user queues, typed job routing
- **Configuration-first:** YAML-driven configuration for jobs, OpenStack, Docker, Triton, and MinIO
- **Testing:** Smoke runtime test, regression suite, and integration tests for WebSockets
- **Documentation:** Full docs in [docs/](docs/), including architecture, configuration, and version stack

---

<a id="features"></a>
## ✨ Features

### 🔐 Security & Stability

- ✅ **WebSocket auth** — Top-level `uuid` required in the first `auth` message
- ✅ **Type validation** — Strict validation for `info`, `management`, and `inference` message types
- ✅ **Config isolation** — YAML config files loaded from `MANAGER/config/`, never committed with secrets
- ✅ **OpenStack credentials** — Application credentials used for Keystone auth (ID + secret)
- ✅ **Token management** — Proactive token refresh and region-aware service catalog (`Catalog` helper)
- ✅ **Graceful shutdown** — uvicorn server shutdown via `server.should_exit = True`

### ⚡ Performance & Operations

- ✅ **Per-user queues** — Fair scheduling and isolation across `info`, `management`, and `inference` jobs
- ✅ **Threaded orchestration** — Dedicated threads for OpenStack, Docker, Triton, jobs, and WebSockets
- ✅ **Creation pipeline** — VM → container → Triton server, with rollback on failures
- ✅ **Deletion pipeline** — Triton → container → VM, with flat and nested payload support
- ✅ **Config-driven behavior** — Jobs, OpenStack, Docker, Triton, and MinIO configured via YAML
- ✅ **Observability** — Structured logging with correlation fields and Prometheus metrics exposed at `/metrics`

### 🧠 Inference Workflows

- ✅ **HTTP inference** — Single request/response via Triton HTTP client
- ✅ **gRPC inference** — Streaming support via Triton gRPC client (planned/experimental; see `docs/ARCHITECTURE.md`)
- ✅ **Routing by IDs** — Uses `vm_id` and `container_id` for routing (aligned with Triton server registration)
- ✅ **Payload examples** — Sample management and inference payloads in [MANAGER/payload_examples/](MANAGER/payload_examples/)

### 🏗 Code Quality & Testing

- ✅ **Dependency Injection** — Job threads receive clear dependencies (Docker, OpenStack, Triton, WebSocket)
- ✅ **Regression tests** — Contracts for DI, deletion normalization, auth, and inference examples
- ✅ **Smoke test** — Validates startup, WebSocket auth, and `queue_stats` with mocks
- ✅ **Internal changelog** — [CHANGELOG_INTERNAL](docs/CHANGELOG_INTERNAL.md) tracks notable engineering changes
- ✅ **Observability stack** — Sample Prometheus + Grafana setup with a ready‑to‑use dashboard (`monitoring/`, `grafana/tcm_dashboard.json`)

### 👥 Target users & use cases

- **Plataformas internas de MLOps (enterprise)**: equipos de plataforma que necesitan orquestar OpenStack, Docker y Triton para dar servicio de inferencia a muchos equipos internos, con colas por usuario/tenant y métricas listas para SRE.
- **Labs de IA y departamentos de innovación**: grupos que prototipan modelos y necesitan un entorno reproducible y observable para probar nuevos modelos en Triton sin pelearse con la infraestructura cada vez.
- **SaaS de inferencia multi‑tenant**: productos que ofrecen inferencia como servicio a múltiples clientes y necesitan aislamiento por tenant, rate limiting, autenticación por roles y una API WebSocket estable + SDK oficial.
- **Equipos SRE / Observabilidad**: organizaciones que ya tienen Prometheus/Grafana y buscan un orquestador con métricas y dashboards serios desde el día 1 (colas, backpressure, tiempos por tipo de job, alertas recomendadas).
- **Integradores backend/frontend**: equipos que solo quieren “hablar con Triton” sin leer el código del manager: consumen la API WebSocket (`/ws`) y el SDK `tcm-client` para lanzar `auth`, `info.queue_stats`, `management` e `inference` con contratos claros.

---

<a id="tech-stack"></a>
## 🛠 Tech Stack

### Backend

- **Language:** Python 3.12+
- **Framework:** FastAPI
- **ASGI server:** uvicorn
- **Configuration:** PyYAML

### Integration

- **OpenStack** — VM creation/deletion via Keystone-authenticated APIs
- **Docker** — Container lifecycle on worker VMs
- **NVIDIA Triton Inference Server** — HTTP/gRPC inference endpoints
- **MinIO / S3** — Model storage via boto3 (optional)

### Development & Testing

- **Tests:** `unittest`, smoke runtime script, WebSocket integration tests (pytest)
- **Environment:** venv inside `MANAGER/` (recommended, especially on WSL/Ubuntu)

---

<a id="requirements"></a>
## 📦 Requirements

- **Python** ≥ 3.12  
  Check: `python3 --version`
- **Virtual environment** (mandatory on Ubuntu/WSL due to PEP 668)  
  Create: `python3 -m venv .venv` (inside `MANAGER/`)
- **OpenStack access** (for full pipeline)  
  - Keystone URL (`OPENSTACK_AUTH_URL`)
  - Application credential ID and secret
- **Docker** running on the host that manages containers
- **Triton Inference Server** images accessible from Docker (for real inference workflows)

> For local development and smoke tests, mocks are used for OpenStack, Docker, and Triton — no external services required.

---

<a id="installation"></a>
## 🚀 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/adrirubim/triton_client_manager.git
cd triton_client_manager
```

### 2. Navigate to `MANAGER`

```bash
cd MANAGER
```

> **Important:** The virtual environment should live **inside** `MANAGER/`, not at the repository root.

### 3. Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

> On Ubuntu/WSL, system-wide `pip install` may fail because of PEP 668. Always use a virtual environment. See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

### 5. Configure

- Ensure `config/*.yaml` exists inside `MANAGER/config/`:
  - `jobs.yaml`
  - `websocket.yaml`
  - `openstack.yaml`
  - `docker.yaml`
  - `triton.yaml`
  - `minio.yaml` (optional)
- Set your environment-specific values (OpenStack URL, application credentials, Docker host, Triton defaults, MinIO, etc.).

See [CONFIGURATION](docs/CONFIGURATION.md) for full details.

### 6. Run the Application

#### Dev mode (recommended for local development)

Runs only `JobThread` + `WebSocketThread` with mocked OpenStack/Docker/Triton backends. No external services required; ideal for experimenting with `/ws`, `/metrics` and the Grafana dashboard.

```bash
cd MANAGER
.venv/bin/python dev_server.py
```

#### Full pipeline (requires real OpenStack/Docker/Triton)

```bash
cd MANAGER
python client_manager.py
```

Startup sequence:

1. OpenStack thread
2. Triton thread
3. Docker thread
4. Job thread
5. WebSocket thread

Each must report ready within 30 seconds or startup fails with `TimeoutError`.

---

<a id="security"></a>
## 🔒 Security

- **Never commit secrets** — Config files should only contain placeholders or non-sensitive defaults. Real credentials must come from environment variables or secret stores.
- **OpenStack credentials** — Use application credentials (ID + secret); treat them as highly sensitive.
- **Docker/Triton** — Protect Docker and Triton endpoints behind firewalls/VPNs; do not expose them directly to the public internet.
- **Logging** — Avoid logging secrets, tokens, or personally identifiable information.
- **Production** — Use strong credentials; restrict network ingress; monitor logs and metrics.

For vulnerability reporting and security guidelines, see [SECURITY.md](SECURITY.md).

---

<a id="documentation"></a>
## 📚 Documentation

All documentation lives under [docs/](docs/). The main index is [docs/README.md](docs/README.md).

| Section          | Links                                                                                                                                                    |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Architecture** | [ARCHITECTURE](docs/ARCHITECTURE.md) · [API_CONTRACTS](docs/API_CONTRACTS.md) · [VERSION_STACK](docs/VERSION_STACK.md)                                  |
| **Operations**   | **[RUNBOOK](docs/RUNBOOK.md)** · **[CONFIGURATION](docs/CONFIGURATION.md)**                                                                             |
| **Development**  | [payload_examples/](MANAGER/payload_examples/) — JSON examples for management and inference payloads                                                    |
| **Testing**      | [TESTING](docs/TESTING.md)                                                                                                                               |
| **Support**      | [TROUBLESHOOTING](docs/TROUBLESHOOTING.md) · [CHANGELOG_INTERNAL](docs/CHANGELOG_INTERNAL.md)                                                           |
| **Policy**       | [CONTRIBUTING](CONTRIBUTING.md) · [SECURITY](SECURITY.md)                                                                                               |

---

<a id="cicd"></a>
## 🔄 CI/CD

GitHub Actions (or any other CI) should run tests and basic checks on every push and pull request to the main branch.

**Recommended pipeline steps (validate stage):**

```bash
cd MANAGER

pip install -r requirements.txt
python -m py_compile client_manager.py
python -m compileall -q classes utils
python tests/smoke_runtime.py
python -m unittest tests.test_regression -v
```

You can mirror this flow in workflows such as [tests.yml](.github/workflows/tests.yml) and [lint.yml](.github/workflows/lint.yml) to keep the main branch healthy.

---

<a id="testing"></a>
## 🧪 Testing

### Health Endpoints

- `GET /health` — Liveness probe
- `GET /ready` — Readiness probe

### Smoke Test

**File:** [`MANAGER/tests/smoke_runtime.py`](MANAGER/tests/smoke_runtime.py)  
**Purpose:** Runtime validation with mocks (JobThread, WebSocket, auth, info).

```bash
cd MANAGER
.venv/bin/python tests/smoke_runtime.py
```

**Expected output:** JSON with `startup`, `auth`, and `info`; exit code 0 on success.

### Regression Tests

**File:** [`MANAGER/tests/test_regression.py`](MANAGER/tests/test_regression.py)  
**Purpose:** Unit tests for dependency injection, deletion normalization, auth, inference contract, and config.

```bash
cd MANAGER
.venv/bin/python -m unittest tests.test_regression -v
```

### WebSocket Integration Tests

**File:** [`MANAGER/tests/test_integration_ws.py`](MANAGER/tests/test_integration_ws.py)  
**Purpose:** Multi-client WebSocket auth and `info` flow.

```bash
cd MANAGER
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest tests/test_integration_ws.py -v
```

Full details and known caveats are documented in [docs/TESTING.md](docs/TESTING.md).

### Full Test Suite (pytest)

For a full local run that matches CI:

```bash
cd MANAGER
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt
.venv/bin/pytest tests/ -v
```

---

<a id="architecture"></a>
## 🏗 Architecture

Triton Client Manager uses a **threaded orchestration architecture** with clear separation of concerns.

**High-level flow:**

```text
WebSocket → JobThread → JobInfo | JobManagement | JobInference
                             ↓
                 OpenStackThread | DockerThread | TritonThread
```

### Backend Components

| Module                | Responsibility                                                    |
| --------------------- | ---------------------------------------------------------------- |
| `client_manager.py`   | Entry point; loads config, wires dependencies, starts threads   |
| `classes/websocket/`  | WebSocket server (FastAPI/uvicorn), auth, type validation       |
| `classes/job/`        | Per-user queues, routing by type (info, management, inference) |
| `classes/openstack/`  | OpenStack auth and VM lifecycle                                 |
| `classes/docker/`     | Docker container lifecycle on worker VMs                        |
| `classes/triton/`     | Triton server lifecycle, health checks, inference               |
| `classes/minio/`      | (If present) MinIO / S3 integration for model storage           |

For in-depth diagrams and contracts, see [ARCHITECTURE](docs/ARCHITECTURE.md) and [API_CONTRACTS](docs/API_CONTRACTS.md).

---

<a id="release-status"></a>
## 📊 Release Status

- **Current release:** `v1.0.0` — **STABLE**
- **Changelog:** see [CHANGELOG.md](CHANGELOG.md) for highlights and upgrade notes.
- **Roadmap completion:** the internal **13-stage project roadmap** has been fully completed and verified (CI, DX, observability, security, SDKs, horizontal scaling).

This repository now represents the **1.0.0 product line** for Triton Client Manager; future changes will follow semantic versioning and be documented in the changelog.

---

<a id="default-users-development"></a>
## ⚠️ Default users (development)

Triton Client Manager does **not** ship with fixed default users. Authentication and authorization are typically handled by the upstream system that connects via WebSocket.

For local development and tests:

- The smoke test and integration tests simulate clients and flows without real user accounts.
- Any production deployment should integrate Triton Client Manager with your own auth backend and user model.

**Security:** Ensure that only trusted backends can connect to the WebSocket interface; treat upstream credentials and network access as sensitive.

---

<a id="useful-commands"></a>
## 🛠 Useful Commands

### Run Application

```bash
cd MANAGER

# Dev server (no external services, recommended for local work)
.venv/bin/python dev_server.py

# Full manager (requires OpenStack/Docker/Triton)
python client_manager.py
```

### Smoke & Regression

```bash
cd MANAGER
.venv/bin/python tests/smoke_runtime.py
.venv/bin/python -m unittest tests.test_regression -v
```

### Official SDKs (Python)

An official Python SDK is published for talking to the Triton Client Manager WebSocket API.

- **Package name:** `tcm-client`  
- **Index (current):** TestPyPI (`https://test.pypi.org/simple/`) – ready to be mirrored to PyPI when desired.

Install from TestPyPI (preferring TestPyPI and falling back to PyPI for dependencies):

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple \
  tcm-client
```

Then use the SDK in your own code:

```python
import asyncio

from tcm_client import AuthContext, TcmWebSocketClient


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"

    ctx = AuthContext(
        uuid="my-frontend-1",
        token="opaque-or-jwt-token",
        sub="user-123",
        tenant_id="tenant-abc",
        roles=["inference", "management"],
    )

    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()
        info = await client.info_queue_stats()
        print(info)


if __name__ == "__main__":
    asyncio.run(main())
```

The SDK is validated by contract tests (`MANAGER/tests/test_client_sdk_contract.py`) and mirrors the
runtime behavior of the internal client in `MANAGER/_______WEBSOCKET/sdk.py`. For full API contract
details, see `docs/API_CONTRACTS.md` / `docs/WEBSOCKET_API.md`.

### Compilation Check

```bash
cd MANAGER
python -m py_compile client_manager.py
python -m compileall -q classes utils
```

### Monitoring stack (Prometheus + Grafana)

From the repository root:

```bash
cd monitoring
docker compose up -d
```

Then:

- Prometheus UI at `http://localhost:9090`
- Grafana UI at `http://localhost:3000` (import `grafana/tcm_dashboard.json` and point it to the `prometheus` data source)

---

<a id="before-pushing-to-github"></a>
## 📤 Before Pushing to GitHub

Before opening a pull request, run the full validation flow locally:

```bash
cd MANAGER
.venv/bin/python tests/smoke_runtime.py --with-ws-client
.venv/bin/python -m unittest tests.test_regression -v
.venv/bin/pytest tests/test_integration_ws.py -v  # optional but recommended
python -m py_compile client_manager.py
python -m compileall -q classes utils
```

All steps should pass before you push to GitHub and open a PR.

---

<a id="contributing"></a>
## 🤝 Contributing

See [CONTRIBUTING](CONTRIBUTING.md) for local checks, branch/commit conventions, and how to open PRs and issues. This is an open-source project (MIT); for inquiries, contact the author.

### Code Standards

- **Python style**: Follow PEP 8 / PEP 20 and project conventions for layout and imports.
- **Tests**: Write tests for new features; keep smoke and regression suites passing.
- **Documentation**: Keep public contracts and behaviors documented (docs and docstrings) in English.
- **Pull Requests**: PRs must pass the [pull request template](.github/PULL_REQUEST_TEMPLATE.md) checklist and GitHub Actions CI.

---

<a id="author"></a>
## 👨‍💻 Author

**Developed by:** [Adrián Morillas Pérez](https://linktr.ee/adrianmorillasperez)

### Connect

- 📧 **Email:** [adrianmorillasperez@gmail.com](mailto:adrianmorillasperez@gmail.com)
- 💻 **GitHub:** [@adrirubim](https://github.com/adrirubim)
- 🌐 **Linktree:** [adrianmorillasperez](https://linktr.ee/adrianmorillasperez)
- 💼 **LinkedIn:** [Adrián Morillas Pérez](https://www.linkedin.com/in/adrianmorillasperez)
- 📱 **Instagram:** [@adrirubim](https://instagram.com/adrirubim)
- 📘 **Facebook:** [AdRubiM](https://facebook.com/adrirubim)

---

<a id="license"></a>
## 📄 License

MIT — See [LICENSE](LICENSE).

---

**Last Updated:** March 2026 · **Status:** Stable (v1.0.0) ✅ · **Stack:** [docs/VERSION_STACK.md](docs/VERSION_STACK.md)

