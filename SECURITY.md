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
2. **Include:**
   - Description of the vulnerability
   - Steps to reproduce (if possible)
   - Impact and suggested fix (optional)

### What to expect

- We will acknowledge receipt as soon as possible.
- We will work on a fix and keep you updated.
- Once fixed, we may publish a security advisory (crediting you if you wish).

---

## Do Not Commit Secrets

- Never commit `.env` files or any file containing real secrets.
- Use `.env.example` as a template for local setup; each environment must provide its own real secrets.
- Do not commit API keys, passwords, access tokens, or private keys.

---

## Safe Handling of Credentials

- Configure credentials only through environment variables or secret managers.
- Avoid logging credentials, tokens, or sensitive payloads.

---

## Dependency Hygiene

- Keep Python dependencies up to date and review security advisories.
- Run audits in CI and test changes in a non‑production environment before deploying major upgrades.
