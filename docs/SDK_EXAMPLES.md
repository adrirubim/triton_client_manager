## SDK `tcm-client` Usage Examples

### Installation

```bash
python -m pip install tcm-client
```

### SDK CLI (`tcm-client-cli`)

The SDK package also provides a minimal CLI (implemented in `sdk/src/tcm_client/cli.py`)
to smoke-test the WebSocket API.

Key defaults:

- `--uri` defaults to `$TCM_WS_URI` or `ws://127.0.0.1:8000/ws`
- `--uuid` defaults to `$TCM_CLIENT_UUID` or `tcm-client-cli`
- `--token` defaults to `$TCM_CLIENT_TOKEN`
- `--sub` defaults to `$TCM_CLIENT_SUB` (or falls back to `uuid` inside the SDK auth client block)
- `--tenant-id` defaults to `$TCM_CLIENT_TENANT_ID` (or falls back to `dev-tenant` inside the SDK auth client block)
- `--vm-ip` (inference only) defaults to `$TCM_VM_IP` when provided

### High-level helper `TcmClient.infer`

```python
from tcm_client.sdk import AuthContext, InferenceInput, TcmClient

auth_ctx = AuthContext(
    uuid="my-client-uuid",
    token="dummy-token",
    sub="user-sdk",
    tenant_id="tenant-sdk",
    roles=["inference", "management"],
)

client = TcmClient("ws://127.0.0.1:8000/ws", auth_ctx)

inputs = [
    InferenceInput(
        name="INPUT__0",
        shape=[1, 3, 224, 224],
        datatype="FP32",
        data=[0.0] * (1 * 3 * 224 * 224),
    )
]

response = client.infer(
    vm_id="vm-1",
    vm_ip="192.0.2.10",
    container_id="ctr-1",
    model_name="example-model",
    inputs=inputs,
)

print(response.type)
print(response.payload)
```

### FastAPI proxy (`examples/fastapi_inference_proxy.py`)

#### 1. Start the manager in DEV mode

```bash
cd /var/www/triton_client_manager
source .venv/bin/activate

# Option A (recommended): installed CLI entrypoint
tcm manager dev

# Option B: run the CLI module directly
python apps/manager/tcm_cli.py manager dev
```

#### 2. Start the FastAPI proxy pointing to the manager

In another terminal:

```bash
cd /var/www/triton_client_manager
source .venv/bin/activate
export TCM_CLIENT_UUID="fastapi-proxy-1"
export TCM_WS_URI="ws://127.0.0.1:8000/ws"
uvicorn examples.fastapi_inference_proxy:app --reload --port 8001
```

#### 3. Example HTTP request:

```bash
curl -X POST \
  "http://127.0.0.1:8001/infer/vm-1/ctr-1/example-model" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "name": "INPUT__0",
      "shape": [1, 3, 224, 224],
      "datatype": "FP32",
      "data": [0.0, 0.0, 0.0]
    }
  ]'
```

### Load test script (`examples/load_test_sdk.py`)

```bash
export TCM_WS_URI="ws://127.0.0.1:8000/ws"
python -m examples.load_test_sdk \
  --vm-id vm-1 \
  --container-id ctr-1 \
  --model-name example-model \
  --concurrency 8 \
  --requests 100
```

