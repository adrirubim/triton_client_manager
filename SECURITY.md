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
- Config files in `MANAGER/config/` may contain placeholders; replace with real values only in deployment environments.
- **SSH keys (`.pem`)**: Never commit private keys. `*.pem` files are in `.gitignore`. Use environment variables or a secret manager (for example `SSH_KEY_PATH`) to supply key paths at runtime.

---

## Safe Handling of Credentials

- Credentials for OpenStack, Docker registry, MinIO / S3, Triton, and similar services must be supplied at runtime (env vars, secret manager, CI secrets).
- Avoid logging credentials, tokens, or full request/response payloads that may contain sensitive data.
- Review `MANAGER/config/` before committing to ensure no accidental credential inclusion.

### WebSocket auth tokens

- The WebSocket entrypoint (`/ws`) accepts an `auth` message whose
  `payload.token` is a JWT-like token issued by your IdP.
- The runtime exposes two high‑level modes, configured via
  `MANAGER/config/websocket.yaml`:
  - `auth.mode: "simple"` (por defecto): la capa de servidor trata el token
    como opaco y sólo puede exigir su presencia (`require_token`). Úsalo en
    desarrollo o cuando la validación criptográfica se haga aguas arriba (API
    gateway, IdP, backend).
  - `auth.mode: "strict"`: el servidor exige token y valida su estructura,
    claims básicos (`exp`, `aud`, `iss` si se configuran) y, opcionalmente, su
    firma si se proporciona material de clave.
- En modo estricto:
  - Si **no** se configuran `jwks_url` ni `public_key_pem`, `utils.auth.validate_token`
    valida únicamente la semántica de claims (formato, `exp`, `iss`, `aud`).
  - Si se configura `jwks_url` (JWKS) o `public_key_pem` (clave pública RSA/ECDSA
    o secreto HS* para dev), `validate_token` usa PyJWT para:
    - Verificar criptográficamente la firma del token.
    - Restringir algoritmos a `auth.algorithms` (por ejemplo `["RS256","ES256"]`).
    - Enforzar `exp`, `aud`, `iss` y `required_claims`.
  - Los tokens inválidos, expirados o con firma no válida producen un mensaje
    de error tipo `error` y el cierre del WebSocket con código `1008`.
- Para entornos regulados:
  - Se recomienda mantener un **IdP o API gateway centralizado** como fuente de
    verdad de autenticación y usar Triton Client Manager detrás de esa capa.
  - `auth.mode: "strict"` + `jwks_url`/`public_key_pem` sirve como refuerzo
    adicional (defensa en profundidad), no como única línea de defensa.

---

## Dependency Hygiene

- Keep dependencies in `MANAGER/requirements.txt` and `MANAGER/requirements-test.txt` up to date.
- Run `pip list --outdated` periodically and review upgrade notes before bumping versions.
- Pin or range-lock versions where stability matters (for example `uvicorn` and other infra components, see `docs/CONFIGURATION.md`).

---

## Logging and Debugging Caution

- Do not log full request/response bodies that may include user data or credentials.
- Prefer structured logs with minimal necessary context.
- In production, avoid verbose stack traces that could expose internal paths, configuration, or infrastructure details.

### Auditability and incident response

- Los logs se generan con formato estructurado (`uuid`, `job`, `type`) y pueden enriquecerse con identidad (`sub`, `tenant_id`, `roles`) procedente del payload de `auth`.
- Buenas prácticas para auditoría:
  - Correlacionar actividades usando el `uuid` de WebSocket (`client_uuid`), el `job_id` y, cuando aplique, los campos de identidad propagados.
  - Usar las métricas Prometheus `tcm_auth_failures_total{reason=...}` y `tcm_rate_limit_violations_total{scope=...}` para detectar patrones de abuso de autenticación o flood de mensajes.
- Flujo recomendado al investigar un incidente de seguridad:
  1. Identificar el `uuid`, `sub` o `tenant_id` implicados a partir de los sistemas aguas arriba.
  2. Filtrar logs por `uuid=<client_uuid>` y, si se registran, por `tenant_id`/`roles` en los mensajes relevantes.
  3. Revisar métricas históricas de:
     - `tcm_auth_failures_total` (motivos de fallo de auth).
     - `tcm_rate_limit_violations_total` (posibles floods).
     - Colas y backpressure (`tcm_queue_*`, `tcm_jobs_rejected_total`).
  4. Tomar medidas correctivas (revocar credenciales en el IdP, bloquear IPs a nivel de red, ajustar límites de rate limiting) y documentar el incidente según las políticas de tu organización.
