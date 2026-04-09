# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-05

### Milestone

- All **13 internal project states** have been completed and verified, covering CI, DX, observability, security, SDKs and horizontal scalability. The internal roadmap for this first product line is now fully realized.

### Highlights

- **JWT Security**
  - Auth model documented and enforced via structured payloads (`token` + `client.*` claims) with validation paths ready for corporate IdPs.
  - Security and auth hardening (trust-no-payload, fail-fast) documented in `SECURITY.md` and `TECHNICAL_GUIDE.md`.

- **Prometheus / Grafana stack**
  - `/metrics` endpoint exposes queue, executor and WebSocket metrics suitable for SRE teams.
  - Local monitoring stack under `infra/monitoring/` (`docker-compose.yml`, `prometheus.yml`) plus a reference Grafana dashboard at `infra/grafana/tcm_dashboard.json`.

- **Multi-replica scaling**
  - Stateless manager design validated in multi-replica scenarios via:
    - `docker-compose.multi-node.yml` with NGINX load balancer.
    - Reference Kubernetes manifests under `infra/k8s/` (Deployment, Service, Ingress, HPA).
  - Runbook guidance for horizontal scaling, backpressure and failover.

- **Official Python SDK**
  - Lightweight WebSocket SDK (`apps/manager/ws_sdk/sdk.py`) providing `AuthContext`, `TcmWebSocketClient` and quickstart helpers.
  - Contract tests (`apps/manager/tests/test_client_sdk_contract.py`) ensure that the documented quickstart (`auth` + `info.queue_stats`) remains compatible with the server.

### Upgrade notes

- Existing deployments should review:
  - `TECHNICAL_GUIDE.md` for operational guidance (monitoring, scaling, Kubernetes, API contracts).
  - `SECURITY.md` for auth and rate-limit recommendations.

