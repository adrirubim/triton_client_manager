# Version Stack

Exact versions used in this project (reference for development and CI). Update when upgrading major dependencies.

## Top Stack (quick visibility)

| Layer | Component | Version | Notes |
|------|-----------|---------|-------|
| Runtime | Python | **3.13** (recommended) | CI validates 3.13; `Dockerfile.manager` uses Python 3.13 |
| Image | Manager base image | `python:3.13-slim` | `Dockerfile.manager` |
| Deployment | Triton Inference Server image | `nvcr.io/nvidia/tritonserver:26.04-py3` | Reference compose under `infra/triton/` |
| Manager | fastapi | 0.136.1 | `apps/manager/requirements.txt` |
| Manager | uvicorn | 0.46.0 | `apps/manager/requirements.txt` |
| Manager | tritonclient | 2.68.0 | `apps/manager/requirements.txt` (pins grpc/http deps explicitly) |

---

## Current environment snapshot (April 2026)

Concrete versions captured from the pinned requirements for the manager runtime (`apps/manager/requirements.txt`).

### Runtime

| Component | Version | Notes |
|----------|---------|-------|
| **Python** | **3.13** (recommended) | CI validates 3.13; `Dockerfile.manager` uses Python 3.13 |

### Triton (reference deployment)

| Component | Version | Notes |
|----------|---------|-------|
| **Triton Inference Server image** | `nvcr.io/nvidia/tritonserver:26.04-py3` | Reference compose under `infra/triton/` |

### Manager (Python dependencies)

| Package | Exact version (`apps/manager/requirements.txt`) |
|---------|-----------------------------------------------|
| **fastapi** | 0.136.1 |
| **uvicorn** | 0.46.0 |
| **wsproto** | 1.3.2 |
| **PyYAML** | 6.0.3 |
| **requests** | 2.33.1 |
| **docker** | 7.1.0 |
| **tritonclient** | 2.68.0 |
| **grpcio** | 1.80.0 |
| **aiohttp** | 3.13.5 |
| **geventhttpclient** | 2.3.9 |
| **numpy** | 2.4.4 |
| **protobuf** | 7.34.1 |
| **boto3** | 1.42.97 |
| **PyJWT[crypto]** | 2.12.1 |

---

## Local verification (CI parity)

```bash
# CI parity (recommended gate): deps + lint + compile + tests + security
bash scripts/check.sh

# Fast local path (assumes repo-root .venv already exists/active)
bash scripts/dev-verify.sh
```

