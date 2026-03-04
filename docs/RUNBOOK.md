# Runbook

Operations and deployment guidance for Triton Client Manager.

---

## Table of Contents

- [Working Directory](#working-directory)
- [Local Setup (Development)](#local-setup-development)
- [How to Run in Dev](#how-to-run-in-dev)
- [Run Application](#run-application)
- [Smoke Test](#smoke-test)
- [Regression Tests](#regression-tests)
- [Startup Assumptions](#startup-assumptions)
- [Pre-Push Validation](#pre-push-validation)
- [Logging and Troubleshooting](#logging-and-troubleshooting)
- [Deployment Examples](#deployment-examples)
- [Backup and Restore](#backup-and-restore)

---

## Working Directory

Run all commands from `MANAGER` or ensure the current working directory is `MANAGER` when starting the application. `client_manager.py` loads `config/*.yaml` relative to the current directory.

## Local Setup (Development)

```bash
cd MANAGER
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-test.txt
```

> **Note:** On Ubuntu/WSL (PEP 668), system-wide `pip install` may fail; use a virtual environment. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## How to Run in Dev

Minimal flow for a new developer:

```bash
cd MANAGER
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt

# Lint & format
black .
ruff check .

# Run tests
pytest

# Start the manager
python client_manager.py
```

See [TESTING.md](TESTING.md) for detailed test commands and [CONFIGURATION.md](CONFIGURATION.md) for config file reference.

## Run Application

```bash
cd MANAGER
python client_manager.py
```

Threads start in order: OpenStack → Triton → Docker → Job → WebSocket. Each must report ready within 30 seconds or startup fails with `TimeoutError`.

## Smoke Test

Uses mocks for OpenStack, Docker, Triton. Validates JobThread DI, WebSocket auth, and info `queue_stats`.

```bash
cd MANAGER
.venv/bin/python tests/smoke_runtime.py
```

**Expected output:** `{"startup": true, "auth": true, "info": true}` (exit 0).

## Regression Tests

Unit tests for DI, deletion normalization, auth contract, inference example, config.

```bash
cd MANAGER
.venv/bin/python -m unittest tests.test_regression -v
```

## Startup Assumptions

| Requirement | Notes |
|-------------|-------|
| OpenStack API | Reachable for full startup |
| Docker API | Reachable |
| Triton | Health checks run against registered servers |
| Config files | Present in `config/` |

With mocks (smoke test), OpenStack/Docker/Triton are not required.

## Pre-Push Validation

Recommended full validation before pushing:

```bash
cd MANAGER
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt

# 1. Lint & format
black .
ruff check . --fix
ruff check .
black --check .

# 2. Smoke + tests
.venv/bin/python tests/smoke_runtime.py --with-ws-client
.venv/bin/pytest tests/ -v

# 3. Optional regression
.venv/bin/python -m unittest tests.test_regression -v

# 4. Optional coverage report
.venv/bin/pytest --cov=classes --cov=utils --cov=client_manager --cov-report=term-missing
# Or HTML report in MANAGER/htmlcov/
.venv/bin/pytest --cov=classes --cov=utils --cov=client_manager --cov-report=html

# 5. Compilation
python -m py_compile client_manager.py
python -m compileall -q classes utils
```

CI pipelines (for example, GitHub Actions) should at minimum run the regression suite and a subset of pytest on pull requests.

## Logging and Troubleshooting

The manager uses a centralized logging configuration in `MANAGER/utils/logging_config.py`.  
Log lines are formatted with correlation fields so you can quickly filter by client or job:

```text
2026-03-02 10:15:33 [classes.job.jobthread] INFO [uuid=client-123 job=job-abc type=inference]: Starting job queue loop
```

- **`uuid`**: WebSocket client UUID (top-level `uuid` of the message).
- **`job`**: Internal job identifier (if applicable).
- **`type`**: High-level job type (for example, `management`, `inference`, `info`).

When you emit logs from application code, you can attach these fields via `extra`:

```python
logger.info(
    "Job accepted",
    extra={"client_uuid": client_uuid, "job_id": job_id, "job_type": "management"},
)
```

Even if a call site omits them, the logger will default to `-` so the format is always safe.

### Filtering logs by client / job

Typical patterns when tailing logs:

- **Filter by client UUID**:

  ```bash
  journalctl -u triton-client-manager.service -f | grep "uuid=client-123"
  ```

- **Filter by job id**:

  ```bash
  journalctl -u triton-client-manager.service -f | grep "job=job-abc"
  ```

- **Focus on inference traffic only**:

  ```bash
  journalctl -u triton-client-manager.service -f | grep "type=inference"
  ```

### Metrics endpoint

The WebSocket server also exposes Prometheus metrics at:

- `GET /metrics` — queue and executor gauges plus WebSocket counters.

Use this endpoint to monitor:

- Total and per‑type queued jobs.
- Executor pending tasks and available worker slots.
- WebSocket connections, disconnections, messages by type, and errors.

## Health and Readiness Probes

The WebSocket server exposes:

- `GET /health` — liveness probe (process up).
- `GET /ready` — readiness probe (server ready to accept WebSocket connections).

Typical Kubernetes probes:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
```

## Deployment Examples

The manager is a long-running process that reads `config/*.yaml` from `MANAGER/config` and exposes the WebSocket server on the configured host/port (default `0.0.0.0:8000`).

### systemd service (single instance)

Example unit file:

```ini
[Unit]
Description=Triton Client Manager
After=network.target

[Service]
Type=simple
WorkingDirectory=/var/www/triton_client_manager/MANAGER
ExecStart=/var/www/triton_client_manager/MANAGER/.venv/bin/python client_manager.py
Restart=on-failure
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable triton-client-manager
sudo systemctl start triton-client-manager
```

### Docker / container runtime

Build a minimal image (example `Dockerfile` snippet):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY MANAGER /app
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "client_manager.py"]
```

Run with config mounted:

```bash
docker run -d \
  -v /var/www/triton_client_manager/MANAGER/config:/app/config:ro \
  -p 8000:8000 \
  --name triton-client-manager \
  triton-client-manager:latest
```

### Kubernetes

Minimal deployment snippet:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: triton-client-manager
spec:
  replicas: 1
  selector:
    matchLabels:
      app: triton-client-manager
  template:
    metadata:
      labels:
        app: triton-client-manager
    spec:
      containers:
        - name: manager
          image: your-registry/triton-client-manager:latest
          ports:
            - containerPort: 8000
          volumeMounts:
            - name: config
              mountPath: /app/config
          readinessProbe:
            httpGet:
              path: /ready
              port: 8000
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
      volumes:
        - name: config
          configMap:
            name: triton-client-manager-config
```

Expose via a `Service` (type `ClusterIP`/`LoadBalancer`) as needed.

## Backup and Restore

The main state is external (OpenStack, Docker, Triton). The manager itself is mostly **stateless**, but you should still protect:

- `MANAGER/config/*.yaml`
- Any TLS keys or certificates referenced from config

### Backup

- **Filesystem backup**:

  ```bash
  tar czf triton_client_manager-config-$(date +%F).tar.gz MANAGER/config
  ```

- **Kubernetes**:
  - Store config in a `ConfigMap` or `Secret` and back it up using your cluster backup solution.

### Restore

- Extract the archived `config/` into the new deployment directory:

```bash
tar xzf triton_client_manager-config-YYYY-MM-DD.tar.gz -C /var/www/triton_client_manager
```

- Restart the service / Deployment so it reloads the configuration.

