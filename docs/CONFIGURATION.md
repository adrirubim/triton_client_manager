# Configuration

Reference for `apps/manager/config/*.yaml`.

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
| `websocket.yaml` | Host, port, valid message types, max message size |
| `openstack.yaml` | Auth, creation/deletion settings |
| `docker.yaml` | Registry, timeouts |
| `triton.yaml` | Health check, creation timeouts |
| `minio.yaml` | Reference template for MinIO/S3 credentials (`access_key`, `secret_key`, `region`); **never store real secrets here**. Actual MinIO config is passed in management payloads or via environment variables. |

## Runtime Assumptions

- Config files are loaded relative to the current working directory.
- `client_manager.py` expects to run with CWD = `apps/manager` (or `config/` reachable).
- Paths in config (e.g. for keys, models) are relative to CWD unless absolute.

## jobs.yaml

| Key | Description |
|-----|-------------|
| `max_queue_size_*_per_user` | Per-user queue limits (backpressure at the per‑user queue level) |
| `max_workers_*` | Worker counts for info, management, inference (thread pool sizes) |
| `max_executor_queue_*` | Executor internal queue sizes (backpressure inside `BoundedThreadPoolExecutor`) |
| `queue_cleanup_interval`, `queue_idle_threshold` | Queue cleanup behavior |
| `info_actions_available` | e.g. `[queue, queue_stats]` |
| `management_actions_available` | e.g. `[creation, deletion, create_vm, ...]` |

## websocket.yaml

| Key | Description |
|-----|-------------|
| `host` | Bind address (e.g. `"0.0.0.0"`) |
| `port` | Listen port (e.g. `8000`) |
| `valid_types` | Allowed message types: `auth`, `info`, `management`, `inference` |
| `max_message_bytes` | Hard limit for incoming WebSocket messages in bytes (default `65536`); messages larger than this are rejected with an error payload and close code `1009` |
| `auth` | Auth hardening configuration (see below) |
| `rate_limits` | Lightweight per-client rate limiting (see below) |

### `websocket.yaml` – auth

```yaml
auth:
  mode: "strict"        # or "simple" (only for dev / behind a strict gateway)
  require_token: true   # recommended default; in dev you may relax it explicitly
  required_claims: []   # e.g. ["exp", "aud", "iss"]
  issuer: null          # expected `iss` claim (optional)
  audience: null        # expected `aud` claim (optional)
  leeway_seconds: 60    # allowed clock skew for `exp`
  jwks_url: null        # optional JWKS endpoint for RSA/ECDSA keys
  public_key_pem: null  # optional PEM-encoded public key (or HS* secret in dev)
  algorithms: []        # e.g. ["RS256", "ES256"], defaults to ["RS256","ES256","HS256"]
```

- **simple**: no local claim validation; the token is treated as opaque and is
  assumed to have been validated upstream (API gateway, IdP, backend).
- **strict** without keys (`jwks_url` / `public_key_pem` empty): a token is
  required and only the **claim semantics** are validated:
  - All claims listed in `required_claims` must be present.
  - `exp` (if present) must not be expired (with `leeway_seconds` of clock
    skew).
  - `iss` / `aud` must match `issuer` / `audience` if configured.
- **strict with keys** (`jwks_url` or `public_key_pem` configured): in addition
  to the above, `utils.auth.validate_token` cryptographically verifies the JWT
  signature using PyJWT, restricting algorithms to `algorithms`.
- In all modes, the `client` block is validated structurally and is used for
  authorization (`roles`).

> **Production guidance:** `mode: "strict"` + `require_token: true` is the
> recommended default. The combination `mode: "simple"` and/or
> `require_token: false` is meant only for controlled development environments
> or when an upstream gateway already enforces strong authentication on every
> request. For production and internet‑exposed deployments, always use
> `mode: "strict"` with `jwks_url` or `public_key_pem` configured and avoid HS*
> tokens outside of dev.

### `websocket.yaml` – rate_limits

```yaml
rate_limits:
  messages_per_second_per_client: 0
  auth_failures_per_minute_per_client: 0
```

- `messages_per_second_per_client`: maximum number of messages allowed per
  second and per client `uuid`. `0` disables the limit.
- `auth_failures_per_minute_per_client`: maximum number of failed `auth`
  attempts allowed per minute and client before the connection is closed. `0`
  disables the limit.

When a limit is exceeded:

- The server sends an `error` message with a descriptive text.
- The connection is closed with code `1008`.
- The following metrics are incremented:
  - `tcm_rate_limit_violations_total{scope="messages"|"auth"}`.

## Distributed rate limiting strategy

The rate limiting defined in `websocket.yaml` is **lightweight and
per-instance**:

- Limits are applied in memory and only affect the replica that receives the
  connection.
- In multi‑replica / multi‑region deployments, it is recommended to delegate
  flood and abuse control to a shared layer:

Typical options:

- **API Gateway / Ingress controller** (Kong, NGINX, Envoy, Traefik):
  - Apply limits by IP, `tenant_id`, or route (`/ws`) before traffic reaches
    the manager.
  - Use rate-limiting plugins/modules backed by Redis or another shared store.
- **Dedicated rate-limiting service**:
  - A microservice that maintains global counters in Redis/Memcached and
    exposes a simple API (`/check_limit`) that the gateway or backend can call.

In these scenarios:

- Configure `rate_limits` in `websocket.yaml` primarily as a **last line of
  defense** per `uuid`, keeping more aggressive limits in the gateway layer.
- Clearly document in your infrastructure which component is the “source of
  truth” for limits (gateway vs backend) and how they coordinate.

### Example: compliance-grade auth + rate limits

For regulated environments, a typical `websocket.yaml` fragment might look like:

```yaml
auth:
  mode: "strict"
  require_token: true
  required_claims: ["exp", "aud", "iss", "sub"]
  issuer: "https://idp.example.com/"
  audience: "tcm"
  leeway_seconds: 60
  # Corporate JWKS endpoint for RSA/ECDSA keys (preferred)
  jwks_url: "https://idp.example.com/.well-known/jwks.json"
  # Or a PEM-encoded public key / HS* secret for dev:
  public_key_pem: null
  algorithms: ["RS256"]

rate_limits:
  messages_per_second_per_client: 20
  auth_failures_per_minute_per_client: 5
```

In this setup:

- Tokens are validated cryptographically via JWKS and must contain the required
  claims.
- Per-replica limits act as a **defence-in-depth** layer on top of global
  limits enforced by your API Gateway / Ingress using a shared backend
  (typically Redis).

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

### Environment file (`.env`)

For local development and simple deployments you can use a `.env` file at the
repository root and let your process manager (or shell) load it before starting
the manager.

- The canonical template lives in: `.env.example`.
- Copy it to `.env` and adjust values for your environment.
- Do **not** commit `.env` to version control.

The template covers at least:

- `TCM_ENV` — runtime environment (`development`, `staging`, `production`).
- `OPENSTACK_...` — auth URL, application credentials, region and SSL verify flag.
- `REGISTRY_TOKEN`, `REGISTRY_TOKEN_NAME` — used by `apps/docker_controller` when
  interacting with a remote container registry.
- Optional `MINIO_...` variables for MinIO/S3-style storage, if you prefer to
  inject credentials via environment variables instead of payloads.
- Optional testing variables (`TCM_RUN_REAL_BACKENDS`, `TCM_REAL_MANAGER_WS_URL`, `TCM_REAL_MODEL_NAME`) used only in controlled environments for integration tests against real backends.

### Environment variables reference (from `.env.example`)

| Variable                     | Purpose                                                                 | Type    | Environments                    | Required |
|------------------------------|-------------------------------------------------------------------------|---------|---------------------------------|----------|
| `TCM_ENV`                    | Runtime environment for the manager and manifests                      | string  | dev / staging / prod           | yes      |
| `TCM_RUN_REAL_BACKENDS`      | Enable integration tests against real OpenStack/Docker/Triton backends | int (0/1) | test / staging (controlled)  | optional |
| `TCM_REAL_MANAGER_WS_URL`    | WebSocket URL of a running manager instance for real-backend tests     | string  | test / staging (when enabled)  | optional |
| `TCM_REAL_MODEL_NAME`        | Name of a real Triton model used in integration tests                  | string  | test / staging (when enabled)  | optional |
| `OPENSTACK_AUTH_URL`         | Keystone authentication endpoint (v3)                                  | string  | staging / prod                 | yes\*    |
| `OPENSTACK_APPLICATION_CREDENTIAL_ID` | OpenStack application credential ID                            | string  | staging / prod                 | yes\*    |
| `OPENSTACK_APPLICATION_CREDENTIAL_SECRET` | OpenStack application credential secret                    | string  | staging / prod                 | yes\*    |
| `OPENSTACK_REGION_NAME`      | OpenStack region name (e.g. `RegionOne`)                               | string  | staging / prod                 | yes\*    |
| `OPENSTACK_VERIFY_SSL`       | Whether to verify SSL certificates when talking to OpenStack           | bool    | all (recommended `true` in prod) | optional (default `true`) |
| `REGISTRY_TOKEN`             | Token with permissions to read from the remote container registry       | string  | staging / prod (and some dev)  | yes\*\*  |
| `REGISTRY_TOKEN_NAME`        | Logical name for the pull token used by the Docker controller           | string  | staging / prod (and some dev)  | optional (required if `REGISTRY_TOKEN` is used) |
| `MINIO_ACCESS_KEY`           | Access key for MinIO/S3-style storage                                  | string  | staging / prod (when used)     | optional |
| `MINIO_SECRET_KEY`           | Secret key for MinIO/S3-style storage                                  | string  | staging / prod (when used)     | optional |
| `MINIO_REGION`               | Region for MinIO/S3-style storage                                      | string  | staging / prod (when used)     | optional |

\* Required only when using the OpenStack integration (full pipeline).  
\*\* Required when `apps/docker_controller` needs to access a private container registry (for example GitLab, GHCR, or an internal registry).

## Other Config Files

`openstack.yaml`, `docker.yaml`, `triton.yaml` are used by `OpenstackThread`, `DockerThread`, and `TritonThread`. Consult the implementing classes for required keys. **Do not commit real credentials**: see `config/openstack.yaml.example` for a template without secrets, and prefer environment variables (`OPENSTACK_...`) for sensitive values.

`minio.yaml` is a reference template (not loaded at startup). MinIO/S3 credentials and endpoint are provided per-request in management payloads (`payload.minio`) or through environment variables such as `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, and `MINIO_REGION`; see `payload_examples/` for structure.

### Queue semantics and backpressure

`JobThread` combines **per‑user bounded queues** (configured via `max_queue_size_*_per_user`) with **bounded executors** (configured via `max_executor_queue_*` and `max_workers_*`). When queues or executors are full:

- New messages for that user/type may be rejected, and a warning is logged.
- Overall saturation can be observed through Prometheus gauges exposed at `/metrics` (see `utils/metrics.py` and `RUNBOOK.md`).

## Version-Sensitive Dependencies

| Dependency | Notes |
|------------|-------|
| **uvicorn** | Minimum `>=0.30.0` (see [VERSION_STACK.md](VERSION_STACK.md)); programmatic lifespan/startup usage in WebSocketThread |
| **Python** | 3.12 supported; dataclass field order matters (e.g. Flavor) |
| **PEP 668** | On Ubuntu 24.04/WSL, use virtual environments; system-wide `pip install` may fail |
| **Dev tools** | `ruff`, `black`, `pytest` and friends live in `requirements-test.txt` and are used by CI workflows (`tests.yml`, `lint.yml`). Install with `pip install -r requirements.txt -r requirements-test.txt` in dev. |
