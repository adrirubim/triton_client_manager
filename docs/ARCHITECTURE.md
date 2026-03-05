# Architecture

Canonical source of truth for Triton Client Manager architecture.

---

## Table of Contents

- [System Overview](#system-overview)
- [Startup Order](#startup-order)
- [Component Map](#component-map)
- [Dependency Injection](#dependency-injection)
- [WebSocket Request Flow](#websocket-request-flow)
- [JobThread Routing](#jobthread-routing)
- [Handler Responsibilities](#handler-responsibilities)
- [Creation Flow](#creation-flow)
- [Deletion Flow](#deletion-flow)
- [Inference Flow](#inference-flow)
- [Integration Points](#integration-points)
- [Failure Domains](#failure-domains)

---

## System Overview

Triton Client Manager is an orchestrator that receives WebSocket requests, routes them by type, and coordinates OpenStack (VM), Docker (container), and Triton Inference Server lifecycle. It exposes inference endpoints for HTTP and gRPC workloads.

## Startup Order

`ClientManager` starts threads in this order:

1. **OpenStack** — VM creation/deletion, info refresh
2. **Triton** — Health checks, server registration, inference
3. **Docker** — Container creation/deletion on VMs
4. **Job** — Orchestration (info, management, inference)
5. **WebSocket** — Accepts client connections

Each thread must report ready before the next starts. Failure raises `TimeoutError`.

## Component Map

| Module | Responsibility |
|--------|----------------|
| `client_manager.py` | Entry point; loads config, wires dependencies, starts threads |
| `classes/websocket/` | WebSocket server (FastAPI/uvicorn), auth, type validation, `send_to_client`, `/health`, `/ready`, `/metrics` |
| `classes/job/` | Per-user queues, routing by type (info, management, inference) |
| `classes/job/info/` | Info requests (e.g. `queue_stats`) |
| `classes/job/management/` | VM, container, Triton creation/deletion pipelines |
| `classes/job/inference/` | Inference to Triton (HTTP implemented; gRPC path experimental/incomplete) |
| `classes/openstack/` | Auth, info, VM creation/deletion |
| `classes/docker/` | Container creation/deletion on OpenStack VMs |
| `classes/triton/` | Triton server lifecycle, health checks, inference clients |
| `utils/bounded_executor.py` | ThreadPool with bounded queue (backpressure) |
| `utils/metrics.py` | Prometheus metrics for WebSocket and job queues/executors |

## Dependency Injection

Dependencies are set by `ClientManager.setup()`:

| Component | Constructor / Wiring |
|-----------|----------------------|
| `JobThread` | Constructed with queue/executor parameters from `config/jobs.yaml`; later receives `docker`, `openstack`, `triton`, `websocket` as attributes before `start()` |
| `JobInfo` | Initialized in `JobThread.start()` with `(docker, openstack, websocket, get_queue_stats)` |
| `JobManagement` | Initialized in `JobThread.start()` with `(docker, triton, openstack, websocket, management_actions_available)` |
| `JobInference` | Initialized in `JobThread.start()` with `(triton, docker, openstack, websocket, inference_actions_available)` |
| Cross-thread | `docker.openstack`, `openstack.websocket`, `triton.websocket` are set in `ClientManager.setup()`; WebSocket uses `get_queue_stats` for metrics |

## WebSocket Request Flow

1. Client connects to `/ws`
2. First message must be `auth` with top-level `uuid`
3. Server responds `auth.ok` and registers client
4. Subsequent messages: `info`, `management`, `inference`
5. Each message requires `uuid`, `type`, `payload`

### Auth and hardening

- El mensaje `auth` puede incluir:
  - `payload.token`: token emitido por tu IdP (opaco o JWT-like).
  - `payload.client`: bloque con `sub`, `tenant_id`, `roles`.
- El servidor:
  - Valida estructuralmente el bloque `client`.
  - Opcionalmente valida claims del token según `websocket.yaml` → `auth`
    (`exp`, `aud`, `iss`, etc.).
  - Asocia el `uuid` autenticado con el contexto `_auth` (`sub`, `tenant_id`,
    `roles`), que se propaga a `JobThread` para decisiones de autorización.
- Rate limiting ligero (en memoria) se aplica por `uuid` cuando se configura
  en `websocket.yaml` → `rate_limits` (mensajes por segundo, reintentos fallidos
  de `auth` por minuto).

## JobThread Routing

| Message type | Handler | Notes |
|--------------|---------|-------|
| `info` | `JobInfo.handle_info` | Action from `payload.action` (e.g. `queue_stats`) |
| `management` | `JobManagement.handle_management` | Action from `payload.action` |
| `inference` | `JobInference.handle_inference` | Protocol from payload (target); HTTP path implemented and covered by tests, gRPC path planned/experimental |

## Handler Responsibilities

| Handler | Responsibility (target design) |
|---------|-------------------------------|
| **JobInfo** | Queries (e.g. `queue_stats`); responses via `websocket(msg_uuid, result)` |
| **JobManagement** | Creation/deletion pipelines; individual actions (`create_vm`, `delete_container`, etc.) |
| **JobInference** | HTTP (single-shot) or gRPC (streaming) inference to Triton — *not fully implemented* |

## Creation Flow

1. `JobCreateVM` → OpenStack VM
2. `JobCreateContainer` → Docker container on VM
3. `JobCreateServer` → TritonThread.create_server (health, load_model, registration)

## Deletion Flow

1. Triton: `delete_server`
2. Docker: `delete_container`
3. OpenStack: `delete_vm`

Deletion is best-effort: failures are collected and reported at the end.

## Inference Flow

High-level design:

- **Protocol selection**: `payload.request.protocol` (`http` or `grpc`); defaults to `http` if absent.
- **HTTP**: one request → one response; on success, a single message is sent back with `status="COMPLETED"` and the handler result in `data`.
- **gRPC**: target design is streaming with multiple responses via `status="ONGOING"` chunks followed by a terminal status; the plumbing exists but is considered experimental/incomplete.

**Current state:**

- The HTTP path is implemented and covered by unit tests in `tests/test_job_management_inference.py`.
- The gRPC path exists but is not yet considered production‑ready; clients should treat HTTP as the stable protocol until documentation and tests for gRPC are extended.

## Integration Points

| External system | Role |
|-----------------|------|
| **OpenStack** | VM creation/deletion, info (flavors, images, networks, etc.) |
| **Docker** | Container creation/deletion on OpenStack VMs |
| **Triton** | Server registration, health checks, HTTP/gRPC inference |

## Failure Domains

| Risk | Mitigation |
|------|------------|
| **Startup order** | Triton starts before Docker; adjust if Triton depends on containers |
| **Alerts** | OpenStack/Docker/Triton use `send_to_first_client`; with multiple clients, alerts go to the first connected client only |
| **Working directory** | `client_manager.py` loads `config/*.yaml` relative to CWD; run from `MANAGER` so `config/` is resolvable |
| **Backpressure** | `JobThread` uses `BoundedThreadPoolExecutor` and per‑user bounded queues; if queues or executors fill, jobs are rejected and warnings are logged — monitor `/metrics` gauges for saturation |
| **Metrics collection** | `/metrics` calls `get_queue_stats`; failures in stats collection are swallowed to keep the endpoint available, but may temporarily expose stale zeros for some gauges |

### Horizontal scaling and multi-region overview

- **Stateless control plane:** cada instancia de Triton Client Manager mantiene
  solo colas y caches en memoria; el estado real vive en OpenStack, Docker y
  Triton.
- **Multi-réplica (una región):**
  - Varias réplicas pueden ejecutarse detrás de un balanceador.
  - Las colas por `uuid` son locales a cada réplica: si un cliente reconecta a
    otra instancia, se crean nuevas colas para ese `uuid`.
  - Para minimizar sorpresas:
    - Usa `uuid` por sesión de conexión.
    - O configura afinidad de sesión en el LB cuando necesites estabilidad
      fuerte por conexión.
- **Multi-región:**
  - Despliega un conjunto Manager + Triton + OpenStack/Docker por región.
  - Usa routing geográfico o por tenant para enviar el tráfico al cluster
    adecuado.
  - Mantén las dependencias (Triton, VMs) en la misma región que el Manager
    para evitar latencias innecesarias.
