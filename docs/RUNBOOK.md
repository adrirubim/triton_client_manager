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

- Arranca únicamente `JobThread` + `WebSocketThread`.
- Usa backends simulados para OpenStack/Docker/Triton (no hace llamadas externas).
- Expone `/ws`, `/health`, `/ready` y `/metrics` en el `host`/`port` de `websocket.yaml`.

Para un entorno **completo** con OpenStack/Docker/Triton reales, utiliza `client_manager.py` como se describe más abajo.

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
  split by scope (`"messages"` para flood de mensajes; `"auth"` para demasiados
  intentos fallidos de autenticación).

### Operational playbooks (backpressure and dependency failures)

#### Queues saturated / backpressure active

- **Síntomas**:
  - `tcm_queue_total_queued` creciendo de forma sostenida.
  - `tcm_executor_*_pending` cerca de su máximo y `tcm_executor_*_available` cerca de 0.
  - Incrementos en `tcm_jobs_rejected_total{type="info|management|inference"}`.
- **Acciones**:
  - Revisar tráfico de entrada (`journalctl ... | grep "type=inference"` / `info` / `management`).
  - Considerar aumentar `max_workers_*` y/o `max_queue_size_*_per_user` (ver `docs/CONFIGURATION.md`), o escalar réplicas del manager.
  - Coordinar con el sistema cliente para aplicar backoff/reintentos exponenciales.

#### Triton no responde o responde con error sistemático

- **Síntomas**:
  - Errores repetidos en logs de `TritonThread` o `TritonInfer`.
  - Jobs de `management` o `inference` con `status: false` y mensajes de fallo de salud/carga de modelo.
  - Posible aumento de `tcm_jobs_rejected_total{type="inference"}` si las colas se llenan.
- **Acciones**:
  - Verificar salud de instancias Triton externas (Kubernetes/VMs) y conectividad de red.
  - Revisar configuración de modelos (nombres, paths, versiones) y logs de Triton.
  - Si es un problema de capacidad, escalar workers Triton o ajustar timeouts y reintentos.

#### OpenStack lento o intermitente

- **Síntomas**:
  - Logs de `OpenstackThread` con timeouts o errores de red.
  - Jobs de `management` con `status: false` en operaciones de creación/eliminación de VMs.
  - Aumento del tiempo de procesamiento para jobs de `management` en `tcm_job_processing_seconds`.
- **Acciones**:
  - Comprobar estado del API de OpenStack y latencias desde el nodo donde corre el manager.
  - Ajustar timeouts y políticas de reintento según documentación de OpenStack.
  - En caso de degradación prolongada, comunicar al equipo de SRE/infra y considerar pausar flujos de creación hasta que se estabilice.

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

Triton Client Manager is **stateless by design**: all estado persistente vive en
OpenStack, Docker y Triton. Cada réplica mantiene únicamente:

- Colas en memoria por `uuid` de cliente.
- Caches locales de VMs, contenedores y servidores Triton.
- Conexiones WebSocket activas con sus propios clientes.

Recomendaciones para escalar a varias réplicas y regiones:

- **Multi-réplica en una región:**
  - Ejecuta varias réplicas del Deployment anterior (`spec.replicas > 1`) detrás
    de un `Service` o balanceador de carga.
  - Cada réplica mantiene sus propias colas por `uuid`. Si un mismo `uuid`
    reconecta contra otra réplica, se crearán colas nuevas para ese cliente en
    esa réplica; los jobs en cola en la réplica anterior no se migran.
  - Para flujos sensibles al estado, se recomienda:
    - Usar `uuid` efímeros por conexión.
    - O bien configurar *sticky sessions* a nivel de LB para mantener el mismo
      cliente en la misma réplica mientras dure la sesión.
  - Las métricas Prometheus deben agregarse por `job`/`instance` para obtener
    una vista de clúster; el dashboard de ejemplo (`grafana/tcm_dashboard.json`)
    puede adaptarse añadiendo filtros por etiqueta de instancia.

- **Multi-región:**
  - Despliegue recomendado: **Manager + Triton + recursos OpenStack/Docker por
    región**.
  - Estrategias típicas de enrutado:
    - DNS geolocalizado (cada cliente se conecta al cluster de su región).
    - Routing explícito por tenant/región en la capa de backend que abre la
      conexión WebSocket (por ejemplo, `tenant_id` → endpoint regional).
  - Consideraciones de latencia:
    - Mantén al cliente lo más cerca posible de la región donde vive Triton y
      los VMs/containers correspondientes.
    - Para frontends globales, es preferible que el servicio backend que abre
      `/ws` esté en la misma región que el cluster de Triton/Manager.

#### Manual validation in scaled deployments

Para validar un despliegue multi-réplica/multi-región sin tests distribuidos
automáticos:

1. **Multi-réplica (una región):**
   - Despliega al menos 2 réplicas del Deployment de Kubernetes o 2 contenedores
     idénticos detrás de un mismo balanceador.
   - Conecta varios clientes (por ejemplo, usando `MANAGER/tests/ws_client_test.py`
     o el SDK `TcmWebSocketClient`) y verifica:
     - Que `auth` + `info.queue_stats` funciona de forma consistente.
     - Que las métricas de cada instancia (`tcm_ws_connections_total`,
       `tcm_queue_total_queued`, etc.) se agregan correctamente en Prometheus.
   - Mata una réplica (por ejemplo, `kubectl delete pod ...`) y confirma que los
     clientes pueden reconectar y seguir usando `auth` + `info.queue_stats` vía
     otra réplica.

2. **Multi-región:**
   - Despliega al menos dos clusters independientes (Manager + Triton +
     OpenStack/Docker) en regiones distintas.
   - Configura un mecanismo de routing (DNS geolocalizado o lógica de backend)
     que envíe cada cliente al cluster de su región.
   - Verifica, para un mismo `tenant_id`, que:
     - Todas las operaciones de `management`/`inference` asociadas a ese tenant
       se dirigen al cluster esperado.
     - La latencia observada es coherente con la distancia cliente‑región.

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

