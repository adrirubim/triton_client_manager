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
- Config files in `apps/manager/config/` may contain placeholders; replace with real values only in deployment environments.
- **SSH keys (`.pem`)**: Never commit private keys. `*.pem` files are in `.gitignore`. Use environment variables or a secret manager (for example `SSH_KEY_PATH`) to supply key paths at runtime.

---

## Safe Handling of Credentials

- Credentials for OpenStack, Docker registry, MinIO / S3, Triton, and similar services must be supplied at runtime (env vars, secret manager, CI secrets).
- Avoid logging credentials, tokens, or full request/response payloads that may contain sensitive data.
- Review `apps/manager/config/` before committing to ensure no accidental credential inclusion.

### WebSocket auth tokens

- The WebSocket entrypoint (`/ws`) accepts an `auth` message whose
  `payload.token` is a JWT-like token issued by your IdP.
- The runtime exposes two high‑level modes, configured via
  `apps/manager/config/websocket.yaml`:
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

---

## Dependency Hygiene

- Keep dependencies in `apps/manager/requirements.txt` and `apps/manager/requirements-test.txt` up to date.
- Run `pip list --outdated` periodically and review upgrade notes before bumping versions.
- Pin or range-lock versions where stability matters (for example `uvicorn` and other infra components, see `docs/CONFIGURATION.md`).

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
