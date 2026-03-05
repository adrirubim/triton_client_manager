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
- [SLOs, Alerts, and Dashboards](#slos-alerts-and-dashboards)
- [Deployment Examples](#deployment-examples)
- [Backup and Restore](#backup-and-restore)
 - [Deploying to Kubernetes](#deploying-to-kubernetes)

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

# Start the DEV server (no OpenStack/Docker/Triton required)
.venv/bin/python dev_server.py
```

This `dev_server.py` entrypoint:

- Starts only `JobThread` + `WebSocketThread`.
- Uses simulated backends for OpenStack/Docker/Triton (no external calls).
- Exposes `/ws`, `/health`, `/ready` and `/metrics` on the `host` / `port`
  configured in `websocket.yaml`.

For a **full** environment with real OpenStack/Docker/Triton, use
`client_manager.py` as described below.

See [TESTING.md](TESTING.md) for detailed test commands and [CONFIGURATION.md](CONFIGURATION.md) for config file reference.

## Run Application

### Full pipeline (requires real OpenStack/Docker/Triton)

```bash
cd MANAGER
python client_manager.py
```

Threads start in order: OpenStack → Triton → Docker → Job → WebSocket. Each must report ready within 30 seconds or startup fails with `TimeoutError`. This is the entrypoint intended for staging/production.

### Dev-only pipeline (no external dependencies)

```bash
cd MANAGER
.venv/bin/python dev_server.py
```

In this mode:

- `OpenstackThread`, `DockerThread` and `TritonThread` are not initialized.
- The WebSocket server and job thread behave like production for `auth`, `info` and queue handling.
- This is the recommended mode to reproduce issues locally and to feed Prometheus/Grafana dashboards.

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

- `GET /metrics` — queue and executor gauges plus WebSocket and job-level counters/histograms.

Use this endpoint to monitor:

- Total and per‑type queued jobs.
- Executor pending tasks and available worker slots.
- WebSocket connections, disconnections, messages by type, and errors.
- Jobs rejected due to backpressure and job processing times by type.

Additional security-related metrics:

- `tcm_auth_failures_total{reason=...}` — total auth failures, split by reason
  (for example, `invalid_payload`, `token`).
- `tcm_rate_limit_violations_total{scope=...}` — total rate limit violations,
  split by scope (`"messages"` for message floods; `"auth"` for too many
  failed authentication attempts).

### Operational playbooks (backpressure and dependency failures)

#### Queues saturated / backpressure active

- **Symptoms**:
  - `tcm_queue_total_queued` growing steadily over time.
  - `tcm_executor_*_pending` close to its maximum and
    `tcm_executor_*_available` close to 0.
  - Increases in `tcm_jobs_rejected_total{type="info|management|inference"}`.
- **Actions**:
  - Inspect incoming traffic (`journalctl ... | grep "type=inference"` /
    `info` / `management`).
  - Consider increasing `max_workers_*` and/or
    `max_queue_size_*_per_user` (see `docs/CONFIGURATION.md`), or scaling
    manager replicas.
  - Coordinate with the client system to apply exponential backoff / retries.

#### Triton not responding or consistently failing

- **Symptoms**:
  - Repeated errors in `TritonThread` or `TritonInfer` logs.
  - `management` or `inference` jobs with `status: false` and error messages
    about health checks or model loading.
  - Possible increase in `tcm_jobs_rejected_total{type="inference"}` if queues
    fill up.
- **Actions**:
  - Check health of external Triton instances (Kubernetes / VMs) and network
    connectivity.
  - Review model configuration (names, paths, versions) and Triton logs.
  - If it is a capacity issue, scale Triton workers or tune timeouts and
    retries.

#### Slow or flaky OpenStack

- **Symptoms**:
  - `OpenstackThread` logs with timeouts or network errors.
  - `management` jobs with `status: false` during VM create/delete operations.
  - Increased processing time for `management` jobs in
    `tcm_job_processing_seconds`.
- **Actions**:
  - Check OpenStack API health and latency from the node where the manager is
    running.
  - Adjust timeouts and retry policies according to OpenStack documentation.
  - For prolonged degradation, coordinate with SRE/infra teams and consider
    pausing creation flows until the platform stabilises.

## SLOs, Alerts, and Dashboards

This section provides reference SLOs, alert rules, and example dashboards to help SRE/operations
teams run Triton Client Manager in production.

### Reference SLOs

These SLOs are suggestions; you should tune them to your environment:

- **WebSocket error rate**
  - **SLO**: WebSocket protocol/application errors \< 1% of total messages over a rolling 5‑minute window.
  - **Signals**: `tcm_ws_errors_total` vs `tcm_ws_messages_total`.

- **Info queue latency**
  - **SLO**: P95 latency of `info.queue_stats` \< 200 ms.
  - **Signals**: HTTP latency from your ingress/load balancer, or a custom histogram in front of `/ws` and `/metrics`.

- **Manager availability**
  - **SLO**: Manager process availability \>= 99.5%.
  - **Signals**: uptime of the Kubernetes Deployment / systemd service; readiness/liveness success rate.

### Example Prometheus alerts (pseudo‑YAML)

You can implement alerts in Prometheus/Alertmanager using rules like:

```yaml
groups:
  - name: triton-client-manager.slo
    rules:
      - alert: TcmHighWebSocketErrorRate
        expr: |
          (
            rate(tcm_ws_errors_total[5m])
            /
            rate(tcm_ws_messages_total[5m])
          ) > 0.01
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High WebSocket error rate in Triton Client Manager"
          description: "Error rate > 1% for more than 10 minutes."

      - alert: TcmManagerNotReady
        expr: up{job="triton-client-manager"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Triton Client Manager is down or not scraping metrics"
          description: "No metrics scraped from job=triton-client-manager for 5 minutes."
```

You can adapt the `job`/labels to match your Prometheus configuration.

### Example Grafana dashboard (what to include)

At minimum, we recommend a Grafana dashboard with panels for:

- **WebSocket traffic**
  - Graph: `rate(tcm_ws_connections_total[5m])` (new connections).
  - Graph: `rate(tcm_ws_messages_total[5m])` split by `type` (auth, info, management, inference).
  - Graph: `rate(tcm_ws_errors_total[5m])` (errors).

- **Queues and backpressure**
  - SingleStat / graph: `tcm_queue_total_queued`.
  - Graphs split by type: `tcm_queue_info_total`, `tcm_queue_management_total`, `tcm_queue_inference_total`.
  - Graph: `tcm_executor_*_pending` and `tcm_executor_*_available` to see executor saturation.
  - Graph: `rate(tcm_jobs_rejected_total[5m])` split by `type`.

- **Dependencies (Triton / OpenStack)**
  - Panels that show health and error rates from:
    - Triton metrics (if you expose them to Prometheus).
    - OpenStack API metrics (HTTP status codes, latency), if available via your infra.

An example dashboard JSON is provided at `grafana/tcm_dashboard.json`. You can import it
directly into Grafana and then customize it for your environment.

## Local Monitoring Stack

To experiment with metrics and the Grafana dashboard locally, you can use the
Docker Compose stack under `monitoring/`:

```bash
cd monitoring
docker compose up -d
```

Requirements:

- Triton Client Manager running on the host at `0.0.0.0:8000` (for example
  with `MANAGER/dev_server.py`).
- Docker Desktop or Docker with support for `host.docker.internal` (on pure
  Linux you can replace the hostname in `prometheus.yml` with the host IP).

Once the stack is up:

- Access Prometheus at `http://localhost:9090` and verify that the
  `triton-client-manager` job scrapes `/metrics`.
- Access Grafana at `http://localhost:3000` (default user/password
  `admin`/`admin`), create a Prometheus datasource pointing to
  `http://prometheus:9090` and import `grafana/tcm_dashboard.json`.

### Day 2 operations checklist

When responding to incidents or degradation, use this checklist:

1. **Is the manager healthy?**
   - Check `/health` and `/ready` endpoints (or Kubernetes probes).
   - Verify `up{job="triton-client-manager"}` in Prometheus.

2. **Is traffic abnormal?**
   - Look at WebSocket connections and messages per type.
   - Check `tcm_ws_errors_total` and error rates.

3. **Are queues/backpressure active?**
   - Check `tcm_queue_total_queued` and per‑type queue gauges.
   - Check `tcm_executor_*_pending` / `tcm_executor_*_available`.
   - Inspect `tcm_jobs_rejected_total{type=...}` to see which job types are being rejected.

4. **Are dependencies failing?**
   - Look for errors in OpenStack, Docker, and Triton logs.
   - Use the operational playbooks above (backpressure, Triton down, OpenStack slow).

5. **Do you need to scale?**
   - If backpressure is sustained and dependencies are healthy:
     - Scale Triton workers (more pods/VMs).
     - Scale Triton Client Manager replicas (see section *Horizontal scaling and multi-region* below).
     - Adjust `max_workers_*` and queue sizes carefully (see `docs/CONFIGURATION.md`).

6. **Post‑incident**
   - Capture a short summary: root cause, impact, and which SLOs were touched.
   - Consider updating alerts, dashboards, or configuration to detect similar issues earlier.

## Multi-Replica Validation Procedure

To validate horizontal scaling behaviour using Docker Compose:

1. Build a manager image:

   ```bash
   docker build -t your-registry/triton-client-manager:latest .
   ```

2. Start the multi-node environment:

   ```bash
   docker compose -f docker-compose.multi-node.yml up -d
   ```

3. Run the SDK quickstart against the NGINX load balancer:

   ```bash
   cd MANAGER
   .venv/bin/python -c "from _______WEBSOCKET.sdk import run_quickstart; run_quickstart('ws://127.0.0.1:8000/ws')"
   ```

   - Verify that you receive a valid `info_response`.

4. Simulate a failover:

   ```bash
   docker stop tcm-manager-1
   ```

   - Re-run the SDK quickstart and confirm that the `auth` + `info.queue_stats`
     flow still works via `tcm-manager-2`.

5. If you are also running the monitoring stack (`monitoring/docker-compose.yml`):

   - Check in Prometheus that metrics from both instances aggregate correctly
     (for example `tcm_ws_connections_total` and `tcm_queue_total_queued`).

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

### Horizontal scaling and multi-region

Triton Client Manager is **stateless by design**: all persistent state lives in
OpenStack, Docker, and Triton. Each replica only maintains:

- In‑memory queues keyed by client `uuid`.
- Local caches of VMs, containers, and Triton servers.
- Active WebSocket connections with its own clients.

Recommendations to scale across replicas and regions:

- **Multi-replica (single region):**
  - Run multiple replicas of the Deployment (`spec.replicas > 1`) behind a
    `Service` or load balancer.
  - Each replica keeps its own queues per `uuid`. If the same `uuid`
    reconnects to another replica, new queues are created there; jobs queued
    on the previous replica are not migrated.
  - For state‑sensitive flows it is recommended to:
    - Use ephemeral `uuid` values per connection.
    - Or configure *sticky sessions* at the LB level so the same client stays
      on the same replica for the duration of the session.
  - Prometheus metrics should be aggregated by `job` / `instance` to obtain a
    cluster‑wide view; the example dashboard (`grafana/tcm_dashboard.json`)
    can be adapted by adding filters per instance label.

- **Multi-region:**
  - Recommended deployment: **Manager + Triton + OpenStack/Docker resources
    per region**.
  - Typical routing strategies:
    - Geo‑DNS (each client connects to the cluster in its region).
    - Explicit tenant/region‑based routing in the backend that opens the
      WebSocket connection (for example, `tenant_id` → regional endpoint).
  - Latency considerations:
    - Keep the client as close as possible to the region where Triton and the
      corresponding VMs/containers live.
    - For global frontends, it is preferable that the backend service that
      opens `/ws` runs in the same region as the Triton/Manager cluster.

#### Manual validation in scaled deployments

To validate a multi‑replica / multi‑region deployment without distributed
automated tests:

1. **Multi-replica (single region):**
   - Deploy at least 2 replicas of the Kubernetes Deployment or 2 identical
     containers behind the same load balancer.
   - Connect several clients (for example using `MANAGER/tests/ws_client_test.py`
     or the `TcmWebSocketClient` SDK) and verify:
     - That `auth` + `info.queue_stats` behave consistently.
     - That metrics from each instance (`tcm_ws_connections_total`,
       `tcm_queue_total_queued`, etc.) aggregate correctly in Prometheus.
   - Kill one replica (for example `kubectl delete pod ...`) and confirm that
     clients can reconnect and continue using `auth` + `info.queue_stats`
     through another replica.

2. **Multi-region:**
   - Deploy at least two independent clusters (Manager + Triton +
     OpenStack/Docker) in different regions.
   - Configure a routing mechanism (geo‑DNS or backend logic) that sends each
     client to the cluster in its region.
   - Verify, for a given `tenant_id`, that:
     - All `management` / `inference` operations for that tenant go to the
       expected cluster.
     - Observed latency matches the expected client‑region distance.

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
 
## Deploying to Kubernetes

This section describes how to deploy Triton Client Manager to Kubernetes using the reference manifests under `k8s/` and how to verify that the Horizontal Pod Autoscaler (HPA) is working as expected.

### Manifests overview (`k8s/`)

The `k8s/` directory contains a minimal but production‑oriented example:

- `k8s/deployment.yaml`
  - `Deployment` for `triton-client-manager` with:
    - Container image (for example `ghcr.io/triton-client-manager/triton-client-manager:latest`).
    - `readinessProbe` on `GET /ready`.
    - `livenessProbe` on `GET /health`.
    - Resource `requests`/`limits` for CPU and memory.
  - `HorizontalPodAutoscaler` (`triton-client-manager-hpa`) targeting the Deployment:
    - `minReplicas` / `maxReplicas` for the manager.
    - CPU utilization target (for example `averageUtilization: 70`).
- `k8s/service.yaml`
  - `Service` exposing the manager pods on port `80` (or `8000`) and targeting container port `8000`.
  - Label selector `app: triton-client-manager`, shared with the Deployment and Ingress.
- `k8s/ingress.yaml`
  - `Ingress` for `triton-client-manager`:
    - Host rule (for example `tcm.example.com`).
    - Path `/` routing to the `triton-client-manager` Service on HTTP.
    - NGINX annotations enabling WebSocket support and appropriate timeouts.

Treat these manifests as a starting point: copy them into your own repo and adjust image, resources, annotations and labels to match your cluster conventions.

### Applying the manifests

From the project root:

```bash
kubectl apply -f k8s/
```

This command will:

- Create or update the `Deployment`, `Service`, `Ingress` and `HorizontalPodAutoscaler` resources.
- Keep them in sync across subsequent changes (you can re‑apply safely after edits).

Typical follow‑up checks:

```bash
kubectl get deploy triton-client-manager
kubectl get svc triton-client-manager
kubectl get ingress triton-client-manager
kubectl get pods -l app=triton-client-manager
```

Once pods are `Ready`, you should be able to:

- Hit `/health` and `/ready` via the Service/Ingress.
- Connect your WebSocket client to the ingress endpoint (for example `wss://tcm.example.com/ws`).
- Scrape `/metrics` from the manager using your Prometheus scrape config.

### Verifying HPA and autoscaling

The reference Deployment includes an `autoscaling/v2` `HorizontalPodAutoscaler` that scales `triton-client-manager` replicas based on CPU utilization.

To inspect the HPA:

```bash
kubectl get hpa triton-client-manager-hpa
kubectl describe hpa triton-client-manager-hpa
```

The `describe` output should show:

- Target Deployment (`scaleTargetRef`).
- Current and target CPU utilization.
- Current number of replicas and desired replicas.

To exercise autoscaling in a non‑production cluster:

1. Ensure you have metrics in place (for example `metrics-server` in a managed Kubernetes cluster).
2. Generate sustained load against the WebSocket endpoint (for example using the Python SDK quickstart or a small load script).
3. Watch the HPA and pods:

   ```bash
   kubectl get hpa triton-client-manager-hpa -w
   kubectl get pods -l app=triton-client-manager -w
   ```

4. After a few minutes under load, the HPA should increase the number of replicas up to `maxReplicas`.
5. When load drops, replicas should gradually scale back down to `minReplicas`.

You can correlate autoscaling behaviour with application metrics (`/metrics`) and your Prometheus/Grafana dashboard:

- Check that per‑instance metrics aggregate correctly as replicas scale.
- Validate that backpressure metrics and queue sizes respond as expected when more replicas are added.
