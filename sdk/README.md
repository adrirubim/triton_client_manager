# tcm-client (Python SDK for Triton Client Manager)

This package provides a small, official Python SDK for talking to the
**Triton Client Manager** WebSocket API.

It wraps the `/ws` endpoint with a high-level client (`TcmWebSocketClient`)
and helpers like `quickstart_queue_stats` so you can integrate without
vendoring code from the server repository.

## Installation

Install from TestPyPI (preferred index for this SDK at the moment):

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple \
  tcm-client
```

## Quickstart

```python
import asyncio

from tcm_client import AuthContext, TcmWebSocketClient


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"

    ctx = AuthContext(
        uuid="sdk-quickstart-client",
        token="opaque-or-jwt-token",
        sub="user-sdk",
        tenant_id="tenant-sdk",
        roles=["inference", "management"],
    )

    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()
        info = await client.info_queue_stats()
        print(info)


if __name__ == "__main__":
    asyncio.run(main())
```

For full API contract details (message format, types and examples), see the
main project documentation in the main repository:

- WebSocket contract: `docs/WEBSOCKET_API.md`
- Architecture and runtime: `docs/ARCHITECTURE.md`

