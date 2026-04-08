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
| `tcm/websocket/` | WebSocket server (FastAPI/uvicorn), auth, type validation, `send_to_client`, `/health`, `/ready`, `/metrics` |
| `tcm/job/` | Per-user queues, routing by type (info, management, inference) |
| `tcm/job/info/` | Info requests (e.g. `queue_stats`) |
| `tcm/job/management/` | VM, container, Triton creation/deletion pipelines |
| `tcm/job/inference/` | Inference to Triton (HTTP implemented; gRPC path experimental/incomplete) |
| `tcm/openstack/` | Auth, info, VM creation/deletion |
| `tcm/docker/` | Container creation/deletion on OpenStack VMs |
| `tcm/triton/` | Triton server lifecycle, health checks, inference clients |
| `utils/bounded_executor.py` | ThreadPool with bounded queue (backpressure) |
| `utils/metrics.py` | Prometheus metrics for WebSocket and job queues/executors |

## Dependency Injection

Dependencies are set by `ClientManager.setup()`:

| Component | Constructor / Wiring |
|-----------|----------------------|
| `JobThread` | Constructed with queue/executor parameters from `config/jobs.yaml`; later receives `docker`, `openstack`, `triton`, `websocket` as attributes before `start()` |
| `JobInfo` | Initialized in `JobThread.start()` with `(docker, openstack, websocket, get_queue_stats)` |
| `JobManagement` | Initialized in `JobThread.start()` with `(docker, triton, openstack, websocket, management_actions_available)` |
| `JobInference` | Initialized in `JobThread.start()` with `(triton, docker, openstack, websocket)` |
| Cross-thread | `docker.openstack`, `openstack.websocket`, `triton.websocket` are set in `ClientManager.setup()`; WebSocket uses `get_queue_stats` for metrics |

## WebSocket Request Flow

1. Client connects to `/ws`
2. First message must be `auth` with top-level `uuid`
3. Server responds `auth.ok` and registers client
4. Subsequent messages: `info`, `management`, `inference`
5. Each message requires `uuid`, `type`, `payload`

### Auth and hardening

- The `auth` message may include:
  - `payload.token`: token issued by your IdP (opaque or JWT-like).
  - `payload.client`: block with `sub`, `tenant_id`, `roles`.
- The server:
  - Validates the `client` block structurally.
  - Optionally validates token claims according to `websocket.yaml` → `auth`
    (`exp`, `aud`, `iss`, etc.).
  - Associates the authenticated `uuid` with the internal `_auth` context
    (`sub`, `tenant_id`, `roles`), which is propagated to `JobThread` for
    authorization decisions.
- Lightweight in‑memory rate limiting is applied per `uuid` when configured in
  `websocket.yaml` → `rate_limits` (messages per second, failed `auth`
  attempts per minute).

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

### Idempotency semantics (management)

- **Creation (`JobCreation`)**
  - orchestrates `create_vm` → `create_container` → `create_server` as a single pipeline;
  - on container failure, attempts to delete the VM;
  - on Triton/server failure, attempts to delete both container and VM;
  - some failure modes (for example, partial success in external systems) cannot be perfectly rolled back, so callers SHOULD treat creation as **at-least-once** and reconcile state explicitly when responses indicate failure.
- **Deletion (`JobDeletion`)**
  - normalizes flat/nested deletion payloads into a single shape and invokes:
    `delete_server` → `delete_container` → `delete_vm`;
  - collects errors from individual steps into a single `JobDeletionFailed` message while still attempting all of them;
  - is designed to be **idempotent at the API level**: repeated deletion requests for already-removed resources will either be treated as no-ops or reported as "not found" without corrupting internal state.

## Inference Flow

High-level design:

- **Protocol selection**: `payload.request.protocol` (`http` or `grpc`); defaults to `http` if absent.
- **Orchestration layer**:
  - `TritonThread` keeps a registry of `TritonServer` instances (`dict_servers[(vm_id, container_id)]`).
  - `TritonInference` (in `classes.triton.inference_orchestrator`) receives a `TritonServer` and a request description (`TritonRequest`) and:
    - parses inputs/outputs (delegating to `TritonInfer`);
    - selects the protocol (`http`/`grpc`);
    - delegates to `TritonInfer` (HTTP/gRPC client);
    - normalizes errors via `TritonInferenceFailed`;
    - supports **simple multi-model pipelines** (a list of `TritonRequest`) executed sequentially.
- **HTTP**:
  - one request → one response;
  - in pipelines, aggregated results are returned as `{model_name: decoded_outputs}`.
- **gRPC**:
  - streaming with multiple `status="ONGOING"` responses followed by `status="COMPLETED"`;
  - chunks are produced from `TritonInference` via `on_chunk(...)` callbacks.

**Current state:**

- `JobInference` (WebSocket layer) selects protocol based on `payload.request.protocol` and:
  - builds a `TritonRequest` with `model_name`, `inputs`, `protocol` and, if applicable, `output_name`;
  - passes it, along with the selected `TritonServer`, to `TritonInference.handle(...)`.
- HTTP, gRPC, and the orchestration layer are covered by:
  - `tests/test_job_inference_handlers.py` (handlers HTTP/gRPC),
  - `tests/test_job_management_inference.py` (JobInference end‑to‑end),
  - `tests/test_triton_infer.py` (TritonInfer + TritonInference, including pipelines and retries).

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
| **Working directory** | `client_manager.py` loads `config/*.yaml` relative to CWD; run from `apps/manager` so `config/` is resolvable |
| **Backpressure** | `JobThread` uses `BoundedThreadPoolExecutor` and per‑user bounded queues; if queues or executors fill, jobs are rejected and warnings are logged — monitor `/metrics` gauges for saturation |
| **Metrics collection** | `/metrics` calls `get_queue_stats`; failures in stats collection are swallowed to keep the endpoint available, but may temporarily expose stale zeros for some gauges |

### Horizontal scaling and multi-region overview

- **Stateless control plane:** each Triton Client Manager instance keeps only
  in‑memory queues and caches; the real state lives in OpenStack, Docker, and
  Triton.
- **Multi-replica (single region):**
  - Multiple replicas can run behind a load balancer.
  - Per‑`uuid` queues are local to each replica: if a client reconnects to a
    different instance, new queues are created for that `uuid`.
  - To minimise surprises:
    - Use a connection‑scoped `uuid` for each WebSocket session.
    - Or configure session affinity on the load balancer when you need strong
      stickiness per connection.
- **Multi-region:**
  - Deploy a Manager + Triton + OpenStack/Docker stack per region.
  - Use geographic or tenant‑based routing to send traffic to the appropriate
    cluster.
  - Keep dependencies (Triton, VMs) in the same region as the Manager to avoid
    unnecessary latency.
