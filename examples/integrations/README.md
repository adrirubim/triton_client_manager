# Integrations — Battle‑Tested Blueprints (v2.0.0‑GOLDEN)

Estos ejemplos están diseñados para integradores que quieren patrones **production‑grade** y alineados con el contrato **v2.0.0‑GOLDEN**.

## 1) High‑Performance Vision Pipeline (SHM + NumPy)

Archivo: `vision_pipeline_shm_numpy.py`

- Escribe un batch NCHW en **POSIX SHM** (`/dev/shm`) con `multiprocessing.shared_memory`.
- Envía al Manager únicamente el **metadato** `SHMReference` (Zero‑Copy Era).

Run:

```bash
python examples/integrations/vision_pipeline_shm_numpy.py \
  --ws-uri "ws://127.0.0.1:8000/ws" \
  --vm-id "vm-1" \
  --container-id "ctr-1" \
  --model-name "resnet50"
```

## 2) Resilient Async Orchestrator (Retries + Backoff)

Archivo: `resilient_async_orchestrator.py`

- Implementa la política recomendada:
  - `SYSTEM_SHUTDOWN`: reconectar con backoff y esperar a que `GET /ready` vuelva a OK.
  - `TRITON_TIMEOUT` con `retriable=true`: reintentar con backoff + jitter y respetar `retry_after_seconds`.

Run:

```bash
python examples/integrations/resilient_async_orchestrator.py \
  --ws-uri "ws://127.0.0.1:8000/ws" \
  --manager-http-base "http://127.0.0.1:8000" \
  --vm-id "vm-1" \
  --container-id "ctr-1" \
  --model-name "resnet50"
```

## 3) Inference Gateway Proxy (FastAPI + TCM)

Archivo: `fastapi_inference_gateway_proxy.py`

- Microservicio FastAPI que actúa como gateway.
- Propaga `error_id` del upstream (`GET /ready`) en su propio `/readyz`.

Run:

```bash
uvicorn examples.integrations.fastapi_inference_gateway_proxy:app --host 0.0.0.0 --port 9010
```

## 4) SRE Monitoring Alerts (Prometheus)

Archivo: `prometheus_alerts.yml`

- Alertas recomendadas sobre:
  - Spikes de `tcm_inference_errors_total{code="TRITON_TIMEOUT"}`
  - Aperturas del circuit breaker (`tcm_circuit_breaker_opens_total`)
  - Ratio alto de fallos asociados a 413 / payload budget (vía `tcm_inference_duration_seconds_count`)
