# Documentation

Central index for Triton Client Manager documentation.

---

## Documentation Index

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, components, flows, dependency injection, failure domains, observability |
| [VERSION_STACK.md](VERSION_STACK.md) | Reference versions (Python, FastAPI, uvicorn, Triton client, etc.) |
| [API_CONTRACTS.md](API_CONTRACTS.md) | WebSocket message formats, auth, payloads, and error contracts |
| [RUNBOOK.md](RUNBOOK.md) | Operations, deployment, validation, health/ready/metrics endpoints |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Canonical dev workflow (venv, installs, CI-like validation) |
| [TESTING.md](TESTING.md) | Smoke, regression, integration, coverage, and linting strategy |
| [CONFIGURATION.md](CONFIGURATION.md) | Config files reference and environment/runtime assumptions |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common issues, root causes, and fixes |
| [CHANGELOG_INTERNAL.md](CHANGELOG_INTERNAL.md) | Engineering changelog (non-marketing) |
| [models/](models/) | Public model cards (per-model technical documentation) |

## Audience and Reading Paths

- **Developers (backend / platform)**:
  - Start with: `README.md` (repo root) → `ARCHITECTURE.md` → `CONFIGURATION.md`.
  - Then: `TESTING.md` for validation and historical context.

- **Operations / SRE**:
  - Start with: `RUNBOOK.md` (day‑to‑day operations) → `TROUBLESHOOTING.md`.
  - Use: `/health`, `/ready`, and `/metrics` endpoints as described in `RUNBOOK.md` and `ARCHITECTURE.md`.

- **Integrators / client teams**:
  - Start with: `API_CONTRACTS.md` for WebSocket contracts and message schemas.
  - Complement with: payload examples in `apps/manager/payload_examples/` and high‑level overview in the root `README.md`.

## Folder Structure (apps/manager)

| Folder | Purpose |
|--------|---------|
| `tcm/` | Core application logic (domain package; wraps internal `classes.*` modules) |
| `config/` | YAML configuration |
| `utils/` | Utilities (e.g. bounded_executor) |
| `payload_examples/` | JSON samples for management and inference |
| `tests/` | Smoke and regression tests |
| `openstack_tools/` | OpenStack-related scripts and utilities |
| `ws_sdk/` | WebSocket client and related code |
