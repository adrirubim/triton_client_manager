# Version Stack

Exact versions used in this project (reference for development and CI). Update when upgrading major dependencies.

## Top Stack (quick visibility)

| Layer | Component | Version | Notes |
|------|-----------|---------|-------|
| Runtime | Python | **3.12** (recommended) | CI validates 3.12; project supports 3.10–3.12 |
| Deployment | Triton Inference Server image | `nvcr.io/nvidia/tritonserver:26.03-py3` | Reference compose under `infra/triton/` |
| Manager | fastapi | 0.135.3 | `apps/manager/requirements.txt` |
| Manager | uvicorn | 0.30.0 | `apps/manager/requirements.txt` |
| Manager | tritonclient[grpc,http] | 2.67.0 | `apps/manager/requirements.txt` |

---

## Current environment snapshot (April 2026)

Concrete versions captured from the pinned requirements for the manager runtime (`apps/manager/requirements.txt`).

### Runtime

| Component | Version | Notes |
|----------|---------|-------|
| **Python** | **3.12** (recommended) | CI validates 3.12; project supports 3.10–3.12 |

### Triton (reference deployment)

| Component | Version | Notes |
|----------|---------|-------|
| **Triton Inference Server image** | `nvcr.io/nvidia/tritonserver:26.03-py3` | Reference compose under `infra/triton/` |

### Manager (Python dependencies)

| Package | Exact version (`apps/manager/requirements.txt`) |
|---------|-----------------------------------------------|
| **fastapi** | 0.135.3 |
| **uvicorn** | 0.30.0 |
| **wsproto** | 1.2.0 |
| **PyYAML** | 6.0.2 |
| **requests** | 2.33.0 |
| **docker** | 7.0.0 |
| **tritonclient[grpc,http]** | 2.67.0 |
| **numpy** | 1.26.0 |
| **protobuf** | 6.33.5 |
| **boto3** | 1.35.0 |
| **PyJWT[crypto]** | 2.12.0 |

---

## Local verification (CI parity)

```bash
./scripts/dev-verify.sh
```

