# tcm-client (Python SDK for Triton Client Manager)

This package provides a small, official Python SDK for talking to the
**Triton Client Manager** WebSocket API.

It wraps the `/ws` endpoint with a high-level client (`TcmWebSocketClient`)
and helpers like `quickstart_queue_stats` so you can integrate without
vendoring code from the server repository.

For full API contract details (message format, types and examples), see the
main project documentation:

- WebSocket contract: `docs/WEBSOCKET_API.md`
- Architecture and runtime: `docs/ARCHITECTURE.md`

