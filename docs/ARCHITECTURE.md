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
| `classes/websocket/` | WebSocket server (FastAPI/uvicorn), auth, type validation, `send_to_client` |
| `classes/job/` | Per-user queues, routing by type (info, management, inference) |
| `classes/job/info/` | Info requests (e.g. `queue_stats`) |
| `classes/job/management/` | VM, container, Triton creation/deletion pipelines |
| `classes/job/inference/` | Inference to Triton (target: HTTP/gRPC; *current implementation has bugs*) |
| `classes/openstack/` | Auth, info, VM creation/deletion |
| `classes/docker/` | Container creation/deletion on OpenStack VMs |
| `classes/triton/` | Triton server lifecycle, health checks, inference clients |
| `utils/bounded_executor.py` | ThreadPool with bounded queue |

## Dependency Injection

Dependencies are set by `ClientManager.setup()`:

| Component | Constructor / Wiring |
|-----------|----------------------|
| `JobThread` | Receives `docker`, `openstack`, `triton`, `websocket` (callbacks) |
| `JobInfo` | `(docker, openstack, websocket, get_queue_stats)` |
| `JobManagement` | `(docker, triton, openstack, websocket, management_actions_available)` |
| `JobInference` | JobThread passes `(docker, openstack, websocket, inference_actions_available, triton)`; `__init__` expects `(triton, docker, ...)` — *order mismatch* |
| Cross-thread | `docker.openstack`, `openstack.websocket`, `triton.websocket` |

## WebSocket Request Flow

1. Client connects to `/ws`
2. First message must be `auth` with top-level `uuid`
3. Server responds `auth.ok` and registers client
4. Subsequent messages: `info`, `management`, `inference`
5. Each message requires `uuid`, `type`, `payload`

## JobThread Routing

| Message type | Handler | Notes |
|--------------|---------|-------|
| `info` | `JobInfo.handle_info` | Action from `payload.action` (e.g. `queue_stats`) |
| `management` | `JobManagement.handle_management` | Action from `payload.action` |
| `inference` | `JobInference.handle_inference` | Protocol from payload (target); *current flow broken* |

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

*Target design* (not fully implemented):

- **HTTP**: one request → one response
- **gRPC**: streaming, multiple responses via `send("ONGOING", chunk)`
- Protocol from `payload.request.protocol` or default `http`

**Current state:** The handlers HTTP/gRPC exist but are not invoked. `handle_inference` has critical bugs (missing `triton_inference`, undefined `action_function`).

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
| **Alerts** | OpenStack/Docker/Triton use `send_to_first_client`; with multiple clients, alerts go to one only |
| **Working directory** | `client_manager.py` loads `config/*.yaml` relative to CWD; run from `MANAGER` |
