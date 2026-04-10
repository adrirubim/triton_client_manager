# tcm-client (Python SDK)

Official Python WebSocket client for **Triton Client Manager**.

## Install

```bash
python -m pip install --upgrade pip
python -m pip install tcm-client
```

## Quickstart (auth + info.queue_stats)

```python
import asyncio

from tcm_client.sdk import quickstart_queue_stats


async def main() -> None:
    result = await quickstart_queue_stats("ws://127.0.0.1:8000/ws")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
```

## CLI

```bash
tcm-client-cli --uri "ws://127.0.0.1:8000/ws" queue-stats
```

