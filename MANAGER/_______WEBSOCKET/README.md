# Triton Client Manager – WebSocket SDK (client)

Small SDK and examples for integrators that want to talk to the Triton Client
Manager WebSocket without reading the server code.

---

## Modules

- `client.py`: very simple interactive client for manual tests (empty `auth` +
  `info.queue_stats`).
- `sdk.py`: lightweight SDK intended for integrators and contract tests.

---

## Quickstart (copy/paste and run)

With the manager running (for example in dev mode with `dev_server.py` on port
`8000`):

```bash
cd MANAGER
.venv/bin/python -c "from _______WEBSOCKET.sdk import run_quickstart; run_quickstart('ws://127.0.0.1:8000/ws')"
```

This command:

1. Opens a WebSocket connection to `ws://127.0.0.1:8000/ws`.
2. Sends an `auth` message with:
   - `uuid`: `sdk-quickstart-client`
   - `payload.client.sub`: `user-sdk`
   - `payload.client.tenant_id`: `tenant-sdk`
   - `payload.client.roles`: `['inference', 'management']`
3. Sends an `info` message with `payload.action = "queue_stats"`.
4. Prints the JSON `info_response` to stdout.

---

## Usage from Python code

```python
import asyncio

from _______WEBSOCKET.sdk import AuthContext, TcmWebSocketClient


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"
    auth_ctx = AuthContext(
        uuid="my-frontend-1",
        token="opaque-or-jwt-token",
        sub="user-123",
        tenant_id="tenant-abc",
        roles=["inference", "management"],
    )

    async with TcmWebSocketClient(uri, auth_ctx) as client:
        await client.auth()
        info = await client.info_queue_stats()
        print(info)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Contract tests

The SDK is validated with `pytest` in `tests/test_client_sdk_contract.py`,
which:

- Starts a test server with `ws_server` (mocks for OpenStack/Docker/Triton).
- Uses `TcmWebSocketClient` to run the `auth` + `info.queue_stats` flow.
- Verifies that the response matches the contract documented in
  `docs/WEBSOCKET_API.md`.

     