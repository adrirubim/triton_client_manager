# Configuration

Reference for `MANAGER/config/*.yaml`.

---

## Table of Contents

- [Config Files](#config-files)
- [Runtime Assumptions](#runtime-assumptions)
- [jobs.yaml](#jobsyaml)
- [websocket.yaml](#websocketyaml)
- [Other Config Files](#other-config-files)
- [Version-Sensitive Dependencies](#version-sensitive-dependencies)

---

## Config Files

| File | Purpose |
|------|---------|
| `jobs.yaml` | Queue sizes, workers, allowed actions |
| `websocket.yaml` | Host, port, valid message types |
| `openstack.yaml` | Auth, creation/deletion settings |
| `docker.yaml` | Registry, timeouts |
| `triton.yaml` | Health check, creation timeouts |
| `minio.yaml` | Reference template for MinIO/S3 credentials (`access_key`, `secret_key`, `region`); actual MinIO config is passed in management payloads |

## Runtime Assumptions

- Config files are loaded relative to the current working directory.
- `client_manager.py` expects to run with CWD = `MANAGER` (or `config/` reachable).
- Paths in config (e.g. for keys, models) are relative to CWD unless absolute.

## jobs.yaml

| Key | Description |
|-----|-------------|
| `max_queue_size_*_per_user` | Per-user queue limits |
| `max_workers_*` | Worker counts for info, management, inference |
| `max_executor_queue_*` | Executor internal queue sizes |
| `queue_cleanup_interval`, `queue_idle_threshold` | Queue cleanup behavior |
| `info_actions_available` | e.g. `[queue, queue_stats]` |
| `management_actions_available` | e.g. `[creation, deletion, create_vm, ...]` |
| `inference_actions_available` | e.g. `[grpc, http]` |

## websocket.yaml

| Key | Description |
|-----|-------------|
| `host` | Bind address (e.g. `"0.0.0.0"`) |
| `port` | Listen port (e.g. `8000`) |
| `valid_types` | Allowed message types: `auth`, `info`, `management`, `inference` |

## OpenStack (auth_url, env vars)

If `auth_url` returns 404, try alternative paths: `/identity/v3/auth/tokens`, `/v3`, or ask your OpenStack admin.

**Environment variables** (override YAML):

| Variable | Overrides |
|----------|-----------|
| `OPENSTACK_AUTH_URL` | auth_url |
| `OPENSTACK_APPLICATION_CREDENTIAL_ID` | application_credential_id |
| `OPENSTACK_APPLICATION_CREDENTIAL_SECRET` | application_credential_secret |
| `OPENSTACK_REGION_NAME` | region_name |
| `OPENSTACK_VERIFY_SSL` | verify_ssl (true/false) |

Example: `export OPENSTACK_AUTH_URL=https://keystone.example.com:5000/v3/auth/tokens`

## Other Config Files

`openstack.yaml`, `docker.yaml`, `triton.yaml` are used by OpenStackThread, DockerThread, TritonThread. Consult the implementing classes for required keys. See `config/openstack.yaml.example` for a template without secrets.

`minio.yaml` is a reference template (not loaded at startup). MinIO/S3 credentials and endpoint are provided per-request in management payloads (`payload.minio`); see `payload_examples/` for structure.

## Version-Sensitive Dependencies

| Dependency | Notes |
|------------|-------|
| **uvicorn** | Minimum `>=0.30.0` (see [VERSION_STACK.md](VERSION_STACK.md)); programmatic lifespan/startup usage in WebSocketThread |
| **Python** | 3.12 supported; dataclass field order matters (e.g. Flavor) |
| **PEP 668** | On Ubuntu 24.04/WSL, use virtual environments; system-wide `pip install` may fail |
