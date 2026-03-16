## Alerting Runbook – Triton Client Manager

This document describes recommended alert rules for Triton Client Manager based
on Prometheus metrics exposed at `/metrics` and the dashboards under
`infra/monitoring/grafana/`.

---

### Queue pressure alerts

**Goal:** Detect sustained queue build‑ups that indicate backpressure or
downstream degradation.

#### High queue size (all jobs)

- **Metric:** `tcm_queue_total_queued`
- **Rule (example):**

```promql
avg_over_time(tcm_queue_total_queued[5m]) > 500
```

- **Action:** Page on‑call when the average total queue length is above 500 for
  more than 5 minutes.

#### High inference queue size

- **Metric:** `tcm_queue_inference_total`
- **Rule (example):**

```promql
avg_over_time(tcm_queue_inference_total[5m]) > 200
```

- **Action:** Investigate Triton health, GPU saturation, and upstream request
  spikes. Consider temporarily throttling clients or scaling out inference
  workers.

---

### Healthcheck / availability alerts

**Goal:** Detect repeated failures on health probes for the manager and Triton.

Assuming you expose:

- `GET /health` – liveness
- `GET /ready` – readiness

and scrape them via blackbox exporter or a custom probe, define:

#### Manager readiness failures

```promql
increase(http_server_requests_seconds_count{path="/ready",status!~"2.."}[5m]) > 0
```

- **Action:** Page SRE if any non‑2xx readiness responses are observed in the
  last 5 minutes in production.

#### Triton healthcheck failures

If you export a numeric gauge `tcm_triton_health{instance="..."}` where `1`
means healthy and `0` means unhealthy:

```promql
avg_over_time(tcm_triton_health[5m]) < 0.5
```

- **Action:** Investigate Triton logs, GPU health, and recent model deployments.

---

### Latency alerts (p95 / p99)

**Goal:** Detect regressions in inference latency, especially at the tail.

Using the histogram `tcm_inference_latency_seconds`, you can create:

#### High p95 latency per model

```promql
histogram_quantile(
  0.95,
  sum(rate(tcm_inference_latency_seconds_bucket[5m])) by (le, model)
) > 0.5
```

- **Meaning:** p95 latency above 500ms for any model over the last 5 minutes.
- **Action:** Drill down by `model` label in the Omega dashboard to identify
  which models are affected and whether the issue is capacity or a regression
  in the model implementation.

#### High p99 latency (global)

```promql
histogram_quantile(
  0.99,
  sum(rate(tcm_inference_latency_seconds_bucket[5m])) by (le)
) > 1
```

- **Meaning:** Global p99 above 1s over the last 5 minutes.
- **Action:** Treat as a high‑severity incident; check queues, Triton, and
  upstream client patterns.

---

### Backend error alerts

**Goal:** Detect elevated error rates for critical backends.

Using `tcm_backend_errors_total{backend="triton|docker|minio|openstack"}`:

#### Increased Triton backend errors

```promql
rate(tcm_backend_errors_total{backend="triton"}[5m]) > 0
```

- **Action:** Investigate Triton logs, recent model rollouts, and GPU health.

#### Increased MinIO errors

```promql
rate(tcm_backend_errors_total{backend="minio"}[5m]) > 0
```

- **Action:** Check MinIO availability, credentials, and network paths from the
  manager.

---

### Operational notes

- Thresholds (`500` jobs, `0.5s`, etc.) are **examples** and should be tuned
  per environment based on historical baselines.
- All alerts should be wired to a clear runbook entry (this file or
  `docs/RUNBOOK.md`) with:
  - Who is responsible (team / rotation).
  - First triage steps.
  - Escalation path.

