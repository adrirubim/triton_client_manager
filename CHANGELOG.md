# Changelog

All notable changes to this project will be documented in this file.

This project follows a practical variant of Semantic Versioning.

- `v1.0.0-ULTIMATE`: hardened, production-grade stabilization line (Resilient Engine).
- `v2.0.0-GOLDEN`: zero-copy era (High-Performance Gateway).

## [v2.0.0-GOLDEN] — 2026-04-22

Production release focused on **Zero‑Copy Shared Memory orchestration** and data-plane evolution.

### Major feature: Zero‑Copy SHM (System Shared Memory)
- Shared-memory inference path for large tensor payloads: clients send **metadata** (`SHMReference`) instead of raw tensor bytes.
- Capability negotiation via `auth.payload.capability` (backwards compatible):
  - legacy clients: `{"type":"auth.ok"}`
  - negotiating clients: `{"type":"auth.ok","payload":{"capability":[...]}}`

### Reliability and safety
- Thread-safe SHM registration cache with LRU eviction (`TritonSHMManager`) to prevent region leaks.
- Typed fatal error codes for SHM failures:
  - `TRITON_SHM_UNAVAILABLE`
  - `TRITON_SHM_REGISTRATION_FAILED`

### Observability
- Added SHM adoption counter:
  - `tcm_inference_shm_requests_total{model,tenant_id}`

## [v1.0.0-ULTIMATE] — 2026-04-21

A 5-phase hardening release focused on forensic stability, correctness under load, and Day-2 operability.

### Features
- Explicit, operator-friendly SRE validation entrypoint via `test_suite_master.sh` with phase-based execution (`--unit`, `--stress`, `--full`).
- Development-safe runtime toggles to disable external dependencies when intentionally unavailable:
  - `TCM_DISABLE_OPENSTACK=1` (development stub)
  - `TCM_DISABLE_DOCKER_REGISTRY=1` (silences registry polling)
- Payload admission control configurable via `max_request_payload_mb` and env override `TCM_MAX_REQUEST_PAYLOAD_MB`.

### Resilience/Hardening
**Phase 1 — Structural Integrity**
- Stabilized internal import paths via compatibility aliases (`classes.*`, `utils.*`) to prevent `ModuleNotFoundError` across different execution contexts (repo root vs `apps/manager`).

**Phase 2 — Resilience**
- Readiness probe hardening with a 1-second TTL cache to reduce downstream fanout during probe storms and high-frequency health checks.
- Improved crash-recovery behavior for Triton registry state rehydration and safer health governance.

**Phase 3 — Protocol Precision**
- Typed Triton error hierarchy (`TritonError`) with explicit `code` and `retriable` semantics to avoid string-parsing contracts.
- Robust inference handler initialization (structural validation instead of `isinstance`) to eliminate aliasing-related false negatives.
- Fast-path handling for expected validation errors (`ValueError`) to prevent stacktrace overhead under load.

**Phase 4 — SRE Hardening**
- gRPC channel hardening (keepalives, message sizing governance, compatibility fallbacks).
- Graceful shutdown with a hard deadline:
  - drains queued work with explicit `SYSTEM_SHUTDOWN` NACKs
  - forces stream cancellation and closes connections on deadline breach
- SIGTERM handling wired to a deterministic `ClientManager.stop()` path (Kubernetes-friendly).

**Phase 5 — Day-2 Operations**
- Operational “copy/paste” workflows validated on WSL: stable loopback networking defaults, deterministic runner phases, and failure diagnostics.

### Observability
- Expanded Prometheus metrics to include operationally relevant labels for post-incident slicing:
  - `tenant_id`, `protocol`, `status`, `code` (where applicable)
- Golden signals for inference:
  - end-to-end duration histogram labeled by `model/protocol/status/code/tenant_id`
  - error classification counter labeled by `model/code/retriable/protocol/tenant_id`
- Readiness TTL caching behavior documented as an O(1) probe path within the TTL window.

### SRE/Testing
- Added load + chaos tools under `apps/manager/devtools/`:
  - High-concurrency WS load tester with 413 payload budget verification
  - `/ready` storm (“flapping backend”) readiness cache validation
  - SIGTERM draining test to validate `SYSTEM_SHUTDOWN` NACK behavior
  - Optional zombie-killer scenario for gRPC stream cancellation (requires real backend/model)
- Improved test robustness for WSL and local environments (filesystem fallbacks, mock correctness, stricter invariants).

---

