#### Recommended auth modes per environment

| Environment | Recommended `auth.mode` | JWT signature                    | HS* tokens                                |
|------------:|-------------------------|----------------------------------|-------------------------------------------|
| `dev`       | `simple` or `strict`    | Optional                         | Allowed for local testing only            |
| `staging`   | `strict`                | Required (JWKS/PEM)              | **Not allowed** (startup will fail)       |
| `prod`      | `strict`                | Required (JWKS/PEM)              | **Not allowed** (startup will fail)       |

# Security Policy

## Supported Versions

We release security updates for the following versions:

| Version | Supported |
| ------- | --------- |
| main    | ✅         |

---

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it **responsibly**.

**Do not** open a public issue for security-sensitive topics.

### How to report

1. **Email:** [adrianmorillasperez@gmail.com](mailto:adrianmorillasperez@gmail.com)  
   Use a descriptive subject, for example: `[Security] triton_client_manager – short description`.
2. **Include (if possible):**
   - Description of the vulnerability
   - Steps to reproduce
   - Impact and affected components
   - Suggested fix or workaround (optional)

### What to expect

- You will receive an acknowledgement as soon as possible.
- A fix will be investigated and you will be kept informed of progress.
- Once fixed, a security advisory may be published (crediting you if you wish).

---

## Do Not Commit Secrets

- Never commit API keys, passwords, tokens, or credentials.
- Use environment variables or secure secret stores for runtime secrets.
- Config files in [`apps/manager/config/`](apps/manager/config/) may contain placeholders; replace with real values only in deployment environments.
- **SSH keys (`.pem`)**: Never commit private keys. `*.pem` files are in [`.gitignore`](.gitignore). Use environment variables or a secret manager (for example `SSH_KEY_PATH`) to supply key paths at runtime.

---

## Safe Handling of Credentials

- Credentials for OpenStack, Docker registry, MinIO / S3, Triton, and similar services must be supplied at runtime (env vars, secret manager, CI secrets).
- Avoid logging credentials, tokens, or full request/response payloads that may contain sensitive data.
- Review [`apps/manager/config/`](apps/manager/config/) before committing to ensure no accidental credential inclusion.

### Registry access tokens (`apps/docker_controller`)

- The helper under `apps/docker_controller/` uses `REGISTRY_TOKEN` / `REGISTRY_TOKEN_NAME` to pull images from a remote container registry and push them into a local registry. The same pattern applies to GitLab, GHCR, Docker Hub, or any other provider, as long as the token has equivalent pull scopes.
- In non-local environments:
  - restrict the registry token to the minimal scope required to **read** container images (for example, `read_registry` in GitLab or the equivalent in your provider);
  - avoid using tokens with admin or write scopes unrelated to image pulls;
  - treat the token as sensitive even when only partially printed in local test scripts.
- Rotate the registry token periodically y en cualquier sospecha de compromiso, y actualiza el entorno / gestor de secretos donde esté configurado.

### Example vs production stacks

- The monitoring stack under `infra/monitoring/` (Prometheus + Grafana) is intended **only for local development**.
- Default credentials such as `GF_SECURITY_ADMIN_USER=admin` / `GF_SECURITY_ADMIN_PASSWORD=admin` must **never** be reused in shared, staging or production environments.
- For any non-local deployment, always override example credentials via secrets or environment-specific configuration and treat monitoring access as sensitive (VPN, restricted ingress, strong auth).

### WebSocket auth tokens

- The WebSocket entrypoint (`/ws`) accepts an `auth` message whose
  `payload.token` is a JWT-like token issued by your IdP.
- The runtime exposes two high‑level modes, configured via
  [`apps/manager/config/websocket.yaml`](apps/manager/config/websocket.yaml):
  - `auth.mode: "simple"` (default): the server treats the token as opaque and
    can only require its presence (`require_token`). Use this in development
    or when cryptographic validation happens upstream (API gateway, IdP,
    backend).
  - `auth.mode: "strict"`: the server requires a token and validates its
    structure, basic claims (`exp`, `aud`, `iss` if configured) and,
    optionally, its signature when key material is provided.
- In strict mode:
  - If **neither** `jwks_url` nor `public_key_pem` is configured,
    `utils.auth.validate_token` validates only claim semantics (shape, `exp`,
    `iss`, `aud`).
  - If `jwks_url` (JWKS) or `public_key_pem` (RSA/ECDSA public key or HS*
    secret for dev) is configured, `validate_token` uses PyJWT to:
    - Verify the token signature cryptographically.
    - Restrict algorithms to `auth.algorithms` (for example
      `["RS256","ES256"]`).
    - Enforce `exp`, `aud`, `iss` and `required_claims`.
  - Invalid, expired, or incorrectly signed tokens produce an `error` message
    and close the WebSocket with code `1008`.
- For regulated environments:
  - Keep a **central IdP or API gateway** as the primary source of
    authentication truth and run Triton Client Manager behind that layer.
  - `auth.mode: "strict"` + `jwks_url` / `public_key_pem` should be treated as
    an additional defence‑in‑depth layer, not the only line of defence.

### Rate limiting: gateway vs manager

- The manager implements **per‑replica, in‑memory rate limiting** for WebSocket traffic,
  configured via [`apps/manager/config/websocket.yaml`](apps/manager/config/websocket.yaml)
  under the `rate_limits` section and surfaced as Prometheus metrics:
  - `tcm_rate_limit_violations_total{scope="messages"|"auth"}`
  - `tcm_unsafe_config_startups_total`
- In production, global rate limiting (per IP / tenant / route) should be enforced
  primarily at the **API gateway / ingress** layer (for example, NGINX, Envoy, Kong),
  using a shared backend (such as Redis) when strict global quotas are required.
- Recommended pattern:
  - Use the gateway as the **source of truth** for global limits and abuse protection.
  - Use Triton Client Manager’s in‑memory limits as a **defence‑in‑depth** mechanism
    to protect individual replicas and to expose detailed metrics for SRE teams.
  - Document which limits live in the gateway and which live in the manager, and
    keep `websocket.yaml`, this `SECURITY.md` and `docs/RUNBOOK.md` in sync when
    policies change.

---

## Dependency Hygiene

- Keep dependencies in [`apps/manager/requirements.txt`](apps/manager/requirements.txt) and
  [`apps/manager/requirements-test.txt`](apps/manager/requirements-test.txt) up to date.
- Run `pip list --outdated` periodically and review upgrade notes before bumping versions.
- Pin or range-lock versions where stability matters (for example `uvicorn` and other infra components, see
  [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)).

### Automated security checks (CI)

- A dedicated **Security** GitHub Actions workflow runs on every push and pull request:
  - **`pip-audit`** against [`apps/manager/requirements.txt`](apps/manager/requirements.txt) and
    [`apps/manager/requirements-test.txt`](apps/manager/requirements-test.txt):
    - The build currently **fails if any vulnerability is detected**.
    - If an exception is ever needed, it must be:
      - Documented in the commit / pull request.
      - Justified in this `SECURITY.md` file (reason, affected package and version, planned mitigation).
  - **`bandit`** SAST scan over [`apps/manager/classes`](apps/manager/classes), [`apps/manager/utils`](apps/manager/utils), and
    [`apps/manager/client_manager.py`](apps/manager/client_manager.py) (tests excluded to reduce noise).
- This policy reflects the current stance: **no known vulnerabilities are accepted** in the main branch without an explicit, documented exception.

---

## Logging and Debugging Caution

- Do not log full request/response bodies that may include user data or credentials.
- Prefer structured logs with minimal necessary context.
- In production, avoid verbose stack traces that could expose internal paths, configuration, or infrastructure details.

### Auditability and incident response

- Logs are generated in a structured format (`uuid`, `job`, `type`) and can be
  enriched with identity (`sub`, `tenant_id`, `roles`) coming from the `auth`
  payload.
- Good practices for auditability:
  - Correlate activity using the WebSocket `uuid` (`client_uuid`), the
    `job_id`, and, when applicable, any propagated identity fields.
  - Use Prometheus metrics `tcm_auth_failures_total{reason=...}` and
    `tcm_rate_limit_violations_total{scope=...}` to detect patterns of auth
    abuse or message floods.
- Recommended flow when investigating a security incident:
  1. Identify the relevant `uuid`, `sub`, or `tenant_id` from upstream
     systems.
  2. Filter logs by `uuid=<client_uuid>` and, if present, by `tenant_id` /
     `roles` in relevant messages.
  3. Review historical metrics for:
     - `tcm_auth_failures_total` (auth failure reasons).
     - `tcm_rate_limit_violations_total` (possible floods).
     - Queue and backpressure metrics (`tcm_queue_*`,
       `tcm_jobs_rejected_total`).
  4. Take corrective action (revoke credentials in the IdP, block IPs at the
     network layer, adjust rate‑limit thresholds) and document the incident in
     line with your organisation’s policies.
