# Documentation

Central index for Triton Client Manager documentation.

---

## Documentation Index

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, components, flows, dependency injection |
| [VERSION_STACK.md](VERSION_STACK.md) | Reference versions (Python, FastAPI, uvicorn, etc.) |
| [API_CONTRACTS.md](API_CONTRACTS.md) | WebSocket message formats, auth, payloads |
| [RUNBOOK.md](RUNBOOK.md) | Operations, deployment, validation |
| [TESTING.md](TESTING.md) | Smoke and regression tests |
| [CONFIGURATION.md](CONFIGURATION.md) | Config files reference |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common issues and fixes |
| [CHANGELOG_INTERNAL.md](CHANGELOG_INTERNAL.md) | Internal engineering changelog |

## Folder Structure (MANAGER)

| Folder | Purpose |
|--------|---------|
| `classes/` | Core application logic |
| `config/` | YAML configuration |
| `utils/` | Utilities (e.g. bounded_executor) |
| `payload_examples/` | JSON samples for management and inference |
| `tests/` | Smoke and regression tests |
| `___openstack___/` | OpenStack-related scripts and utilities |
| `_______WEBSOCKET/` | WebSocket client and related code |
