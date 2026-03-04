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
