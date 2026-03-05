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
  - Security runbook and metrics for authentication failures and rate limiting (`tcm_auth_failures_total`, `tcm_rate_limit_violations_total`) captured in `SECURITY.md` and `docs/RUNBOOK.md`.

- **Prometheus / Grafana stack**
  - `/metrics` endpoint exposes queue, executor and WebSocket metrics suitable for SRE teams.
  - Local monitoring stack under `monitoring/` (`docker-compose.yml`, `prometheus.yml`) plus a reference Grafana dashboard at `grafana/tcm_dashboard.json`.

- **Multi-replica scaling**
  - Stateless manager design validated in multi-replica scenarios via:
    - `docker-compose.multi-node.yml` with NGINX load balancer.
    - Reference Kubernetes manifests under `k8s/` (Deployment, Service, Ingress, HPA).
  - Runbook guidance for horizontal scaling, backpressure and failover.

- **Official Python SDK**
  - Lightweight WebSocket SDK (`_______WEBSOCKET/sdk.py`) providing `AuthContext`, `TcmWebSocketClient` and quickstart helpers.
  - Contract tests (`MANAGER/tests/test_client_sdk_contract.py`) ensure that the documented quickstart (`auth` + `info.queue_stats`) remains compatible with the server.

### Upgrade notes

- Existing deployments should review:
  - `docs/RUNBOOK.md` for updated operational guidance (monitoring, scaling, Kubernetes).
  - `SECURITY.md` for auth and rate-limit recommendations.
  - `docs/WEBSOCKET_API.md` and `MANAGER/_______WEBSOCKET/README.md` for the SDK quickstart and message contracts.

