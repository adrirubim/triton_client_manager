# Version Stack

Exact versions used in this project (reference for development and CI). Update when upgrading major dependencies.

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

---

## 👨‍💻 Author

**Developed by:** [Adrián Morillas Pérez](https://linktr.ee/adrianmorillasperez)

### Connect

- 📧 **Email:** [adrianmorillasperez@gmail.com](mailto:adrianmorillasperez@gmail.com)
- 💻 **GitHub:** [@adrirubim](https://github.com/adrirubim)
- 🌐 **Linktree:** [adrianmorillasperez](https://linktr.ee/adrianmorillasperez)
- 💼 **LinkedIn:** [Adrián Morillas Pérez](https://www.linkedin.com/in/adrianmorillasperez)
- 📱 **Instagram:** [@adrirubim](https://instagram.com/adrirubim)
- 📘 **Facebook:** [AdRubiM](https://facebook.com/adrirubim)

---

## 📄 License

MIT — See [LICENSE](LICENSE).

---

**Last Updated:** April 2026 · **Status:** Stable ✅ · **Version:** v1.0.0 · **Stack:** This file

# Version Stack

Canonical version reference for Triton Client Manager (manager runtime under `apps/manager/`).

**Last updated:** April 2026

---

## Runtime

| Component | Version |
|----------|---------|
| Python (recommended) | **3.12** |
| Python (supported) | 3.10 – 3.12 |

---

## Triton (reference deployment)

| Component | Version |
|----------|---------|
| Triton Inference Server image | `nvcr.io/nvidia/tritonserver:26.03-py3` |

---

## Manager dependencies (source of truth = `apps/manager/requirements.txt`)

This repository pins its runtime/test tooling in `apps/manager/requirements.txt`. Key pins:

| Package | Pinned |
|---------|--------|
| fastapi | `0.135.3` |
| uvicorn | `0.30.0` |
| wsproto | `1.2.0` |
| PyYAML | `6.0.2` |
| requests | `2.33.0` |
| docker | `7.0.0` |
| tritonclient[grpc,http] | `2.67.0` |
| numpy | `1.26.0` |
| protobuf | `6.33.5` |
| boto3 | `1.35.0` |
| PyJWT[crypto] | `2.12.0` |

---

## Local verification (CI parity)

```bash
./scripts/dev-verify.sh
```

