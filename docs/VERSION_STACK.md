# Version Stack

Reference for Triton Client Manager (`apps/manager`). `requirements.txt` uses minimum versions; upgrade to latest with `pip install -r requirements.txt -r requirements-test.txt --upgrade`.

**Last updated:** March 2026

## Runtime

| Component | Minimum |
|-----------|---------|
| Python | 3.12+ |

## Core Dependencies

| Package | Minimum |
|---------|---------|
| fastapi | 0.115.0 |
| uvicorn | 0.30.0 |
| wsproto | 1.2.0 |
| PyYAML | 6.0.2 |

## Integration

| Package | Minimum |
|---------|---------|
| requests | 2.32.0 |
| docker | 7.0.0 |
| tritonclient | 2.48.0 |
| boto3 | 1.35.0 |

## Triton Inference

| Package | Minimum |
|---------|---------|
| numpy | 1.26.0 |
| protobuf | 5.26.0 |

## Test / Dev Dependencies

| Package | Minimum |
|---------|---------|
| pytest | 9.0.0 |
| pytest-asyncio | 0.23.0 |
| websockets | 12.0 |
| coverage | 7.6.0 |
| black | 24.4.0 |
| ruff | 0.5.0 |
| isort | 5.13.0 |

## Upgrade

```bash
cd apps/manager
.venv/bin/pip install -r requirements.txt -r requirements-test.txt --upgrade
```

Then run the full test suite to verify:

```bash
.venv/bin/python tests/smoke_runtime.py --with-ws-client
.venv/bin/python -m unittest tests.test_regression -v
.venv/bin/pytest tests/test_integration_ws.py -v
```

## Upgrade Constraints (tritonclient)

**tritonclient 2.65.0** (latest on PyPI) imposes upper bounds on:

| Package | Constraint | Effect |
|---------|------------|--------|
| grpcio | &lt;1.68 | Cannot upgrade to grpcio 1.68+ |
| protobuf | &lt;6.0dev | Cannot upgrade to protobuf 6.x |

Until **tritonclient 2.66** is released on PyPI (planned with Triton 26.02), grpcio and protobuf remain pinned. FastAPI, uvicorn, and other dependencies can be upgraded normally.

See [triton-inference-server/client#869](https://github.com/triton-inference-server/client/issues/869) (protobuf 6) and [PR #862](https://github.com/triton-inference-server/client/pull/862) (grpcio &ge;1.68).

## WebSocket Implementation

We use `ws="wsproto"` in uvicorn to avoid `DeprecationWarning` from `websockets.legacy` (uvicorn's default implementation still uses the deprecated API).

**Client-side note:** depending on the installed `websockets` version and layout, the import path for `connect` may vary. In this repository we use `from websockets.client import connect` in tests for compatibility, and the packaged SDK includes a fallback between `websockets.asyncio.client` and `websockets.client`.
