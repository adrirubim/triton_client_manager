# Security

---

## Table of Contents

- [Do Not Commit Secrets](#do-not-commit-secrets)
- [Safe Handling of Credentials](#safe-handling-of-credentials)
- [Dependency Hygiene](#dependency-hygiene)
- [Logging Caution](#logging-caution)
- [Reporting Vulnerabilities](#reporting-vulnerabilities)

---

## Do Not Commit Secrets

- Never commit API keys, passwords, tokens, or credentials.
- Use environment variables or secure secret stores for runtime secrets.
- Config files in `MANAGER/config/` may contain placeholders; replace with real values only in deployment environments.

## Safe Handling of Credentials

- OpenStack, Docker registry, MinIO, and similar credentials must be supplied at runtime or via environment.
- Avoid logging credentials or sensitive payloads.
- Review `MANAGER/config/` before committing; ensure no accidental credential inclusion.
- **SSH keys (`.pem`)**: Never commit private keys. `*.pem` files are in `.gitignore`. Use environment variables or a secret manager (e.g. `SSH_KEY_PATH`) to supply key paths at runtime.

## Dependency Hygiene

- Keep dependencies in `MANAGER/requirements.txt` up to date.
- Run `pip list --outdated` periodically and update with care.
- Pin versions where stability matters (e.g. uvicorn range per [docs/CONFIGURATION.md](docs/CONFIGURATION.md)).

## Logging Caution

- Do not log full request/response payloads that may contain user data.
- Avoid logging stack traces or errors that could expose internal paths or configuration.

## Reporting Vulnerabilities

To report a security vulnerability:

| Field | Value |
|-------|-------|
| **Contact** | Configure via GitHub repository settings (Settings → Security) or use `security@your-org.com` (replace with your org contact). |
| **Include** | Description, steps to reproduce, impact, and suggested fix (if any). |
| **Disclosure** | Allow reasonable time for a fix before public disclosure. |
