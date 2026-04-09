# Technical Guide — Triton Client Manager (v1.0.0)

Single **Flat Master Docs** technical guide for this repository.
If this guide disagrees with the code, **the code wins**.

---

## Table of Contents

- [Architecture](#architecture)
- [Security](#security)
- [Resilience](#resilience)
- [QoS & Fairness (DRR)](#qos--fairness-drr)
- [Observability](#observability)
- [Deployment Guardrails](#deployment-guardrails)
- [Key Files](#key-files)
- [Authorship & Maintenance](#authorship--maintenance)

---

## Architecture

### High-level data path

The manager is a threaded control plane that routes WebSocket messages into typed job pipelines:

```text
WebSocket (/ws)
  → WebSocketThread (FastAPI/uvicorn; validates envelope; injects _correlation_id; attaches _auth)
    → JobThread (queues + scheduling)
      → JobInfo | JobManagement | JobInference
        → OpenStackThread | DockerThread | TritonThread
            → TritonInfer / InferenceOrchestrator (HTTP + gRPC)
```

### Message envelope and routing

- **Envelope (required)**: `uuid` (string), `type` (`auth|info|management|inference`), `payload` (object)
- **Internal fields (server-only)**:
  - `_correlation_id`: UUID4 per inbound message (for tracing)
  - `_auth`: derived auth context after `auth` (`sub`, `tenant_id`, `roles`)

### Thread startup order

In full mode (`apps/manager/client_manager.py`), threads start in order:

1. OpenStack
2. Triton
3. Docker
4. Job
5. WebSocket

In dev mode (`apps/manager/dev_server.py`), only **Job + WebSocket** are started (mocked backends).

---

## Security

### Zero-Trust authorization model (JWT claims only)

**Source of truth**: `apps/manager/utils/auth.py` + enforcement in `apps/manager/classes/websocket/websocketthread.py`.

- In `auth.mode: "strict"`, identity and authorization are derived **exclusively** from validated JWT claims:
  - `sub` from `claims["sub"]`
  - `tenant_id` from `claims["tenant_id"]` (fallback `claims["tenant"]`)
  - `roles` from `claims["roles"]` / `claims["role"]` / `claims["permissions"]`
- Client-provided `payload.client.*` exists for SDK ergonomics and dev tooling, but must **not** grant privileges in strict mode.

### Fail-fast on insecure configuration

Outside development (`TCM_ENV != "development"`), the server refuses to start if auth is insecure:

- `auth.mode == "simple"` OR `auth.require_token == false` → **startup fails** (`SECURITY_FAIL_FAST`)
- `auth.mode == "strict"` but missing `jwks_url`/`public_key_pem` → **fails fast** (`SecurityError`)
- HS* algorithms are allowed only in development and must be explicitly configured

### Path Traversal protection (model repository)

When scaffolding models into the local Triton model repository, the domain layer applies two defenses:

- **Regex allowlist** for model names:
  - `^[a-zA-Z0-9._-]+$`
- **Path containment**:
  - final path must remain within `<repo_root>/infra/models` using `Path.resolve()` and `relative_to(...)`

Implementation: `src/Domains/Models/Actions/ScaffoldModelAction.py`.

### `config.pbtxt` string sanitization

To avoid pbtxt injection / invalid config generation, pbtxt string fields are sanitized:

- forbidden: `"`, `\n`, `\r`, `\t`
- replacement: `_` (empty → `"UNNAMED"`)

Implementation: `src/Domains/Models/Analysis/TritonConfigBridge.py`.

---

## Resilience

### Auto-healing + stale/zombie eviction (Triton backends)

**Source of truth**: `apps/manager/classes/triton/tritonthread.py`.

The manager tracks per-server health and applies governance configured via `apps/manager/config/triton.yaml`:

- **Stale/zombie eviction**:
  - evict after `health_failure_evict_threshold` consecutive health failures, and/or
  - evict if `last_healthy_ts` is older than `stale_evict_seconds`
- **Active healing (restart)**:
  - after `active_heal_restart_threshold` failures, attempt container restart
  - enforce cooldown: `active_heal_restart_cooldown_seconds`

### Circuit breaker (inference fail-fast)

**Source of truth**: `apps/manager/classes/triton/inference_orchestrator.py` and `apps/manager/classes/job/inference/inference.py`.

- Tracks consecutive inference failures per `TritonServer`
- If failures exceed `circuit_breaker_failure_threshold`, circuit opens for `circuit_breaker_open_seconds`
- When open:
  - requests fail fast
  - clients receive structured degraded response (`DEGRADED_CIRCUIT_OPEN`) including `retry_after_seconds`

### Atomicity & operational integrity

The management pipelines are designed as **step-based orchestration** with explicit rollback paths:

- **Creation**: VM → container → Triton server (rollback best-effort on partial failure)
- **Deletion**: Triton → container → VM (best-effort, idempotent shape normalization)

### Crash recovery (orchestrator amnesia protection)

The Triton server registry is mirrored to a lightweight JSONL file:

- file: `state/servers.jsonl` (append-style audit trail of server lifecycle/state)
- on startup: rehydrate registry, rebuild lightweight clients, verify readiness

---

## QoS & Fairness (DRR)

### Priority ordering (prevent low-value blocking)

Dispatch cycle is ordered:

1. **inference**
2. management
3. info

This reduces the chance that large/slow `info` traffic delays inference under contention.

### DRR (Deficit Round Robin) fairness model

**Source of truth**: `apps/manager/classes/job/jobthread.py`.

Scheduling is **budget-based** over `tenant_id`:

- Each active tenant has a deficit counter per job type.
- Each cycle:
  - add quantum to each active tenant
  - dispatch only if `deficit >= cost(job_type)`
  - subtract cost when dispatched

Governance is configured in `apps/manager/config/jobs.yaml` under `qos` (validated by `apps/manager/config_schema.py`):

- `base_quantum`
- `job_type_costs` (e.g. inference=10, management=5, info=1)
- `tenant_quantum_multipliers` (optional)
- legacy compatibility:
  - `job_type_weights`
  - `tenant_weights`

### Semantic backpressure (budget throttling)

When DRR budgets throttle a tenant, the system may emit a best-effort warning:

- `BACKPRESSURE_INSUFFICIENT_BUDGET`

This is a **delay signal**, not a drop. Under hard saturation, per-user queues/executors can still reject work.

---

## Observability

### Correlation IDs (hashed)

- `_correlation_id` is injected for every inbound message.
- Logs emit a **hashed** `correlation_id` (via `safe_log_id(...)`) as `sha256:<12-hex>`.
- There is no separate manager `request_id`; use `uuid + corr + type`.

### `/metrics` endpoint access gate

`GET /metrics` is restricted to **loopback/private IPs** only:

- allowed: `ip.is_loopback` or `ip.is_private`
- otherwise: **403**

### Prometheus metrics (custom)

Defined in `apps/manager/utils/metrics.py` (selected highlights):

- WebSocket: `tcm_ws_connections_total`, `tcm_ws_messages_total{type}`, `tcm_auth_failures_total{reason}`
- Rate limiting: `tcm_rate_limit_violations_total{scope}`, `tcm_unsafe_config_startups_total{reason}`
- Queues/executors: `tcm_queue_*`, `tcm_executor_*`, `tcm_jobs_rejected_total{type}`
- Inference: `tcm_inference_latency_seconds{model}`, `tcm_backend_errors_total{backend}`
- Model analysis: `tcm_model_analysis_issues_total{code}`
- QoS/DRR: `tcm_qos_slots_consumed_total{tenant_id,job_type}`, `tcm_qos_deficit_spent_total{tenant_id,job_type}`

---

## Deployment Guardrails

### Reference Triton stack

`infra/triton/docker-compose.yml` uses:

- image: `nvcr.io/nvidia/tritonserver:26.03-py3`
- guardrails (reference):
  - `shm_size: "2gb"`
  - CPU/RAM caps (tune per environment)

### Recommended Python environment

- canonical venv: repo-root `.venv/`
- runtime pins: see `VERSION_STACK.md` and `apps/manager/requirements.txt`

---

## Key Files

- **Manager runtime**
  - `apps/manager/client_manager.py` (full startup)
  - `apps/manager/dev_server.py` (dev mode, mocked backends)
  - `apps/manager/classes/websocket/websocketthread.py` (WS server, `/metrics` gate, auth enforcement)
  - `apps/manager/classes/job/jobthread.py` (queues + DRR)
  - `apps/manager/classes/triton/tritonthread.py` (health, persistence, auto-heal)
  - `apps/manager/classes/triton/inference_orchestrator.py` (circuit breaker)
  - `apps/manager/utils/metrics.py` (Prometheus metrics)
  - `apps/manager/utils/auth.py` (JWT validation + fail-fast)

- **Domain model tooling**
  - `src/Domains/Models/Analysis/PyTorchInspector.py` (ZIP EOCD safety)
  - `src/Domains/Models/Analysis/TritonConfigBridge.py` (pbtxt generation + sanitization)
  - `src/Domains/Models/Actions/ScaffoldModelAction.py` (path traversal protections)

---

## Authorship & Maintenance

**Developed by:** [Adrián Morillas Pérez](https://linktr.ee/adrianmorillasperez)

### Connect

- 📧 **Email:** [adrianmorillasperez@gmail.com](mailto:adrianmorillasperez@gmail.com)
- 💻 **GitHub:** [@adrirubim](https://github.com/adrirubim)
- 🌐 **Linktree:** [adrianmorillasperez](https://linktr.ee/adrianmorillasperez)
- 💼 **LinkedIn:** [Adrián Morillas Pérez](https://www.linkedin.com/in/adrianmorillasperez)
- 📱 **Instagram:** [@adrirubim](https://instagram.com/adrirubim)
- 📘 **Facebook:** [AdRubiM](https://facebook.com/adrirubim)

---

## 📄 License

MIT — See [LICENSE](LICENSE).

---

**Last Updated:** April 2026 · **Status:** Stable ✅ · **Version:** v1.0.0 · **Stack:** [VERSION_STACK.md](VERSION_STACK.md)

