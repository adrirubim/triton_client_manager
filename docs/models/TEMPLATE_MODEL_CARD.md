# MODEL_NAME – Model Card (Template)

## Purpose

Short description of what this model does and in which scenarios it should be
used.

## Format and Location

- **Format:** ONNX / safetensors / gguf / engine
- **Repository path:** `infra/models/MODEL_NAME/`
- **Config file:** `infra/models/MODEL_NAME/config.pbtxt`
- **Weights:** `infra/models/MODEL_NAME/1/weights/model.onnx`

## Inputs / Outputs

Describe the main inputs and outputs as exposed via Triton.

### Inputs

- **`INPUT_NAME`**
  - `data_type`: `TYPE_FP32` (or appropriate)
  - `shape`: `[BATCH, ...]`
  - **Description:** What this tensor represents.

### Outputs

- **`OUTPUT_NAME`**
  - `data_type`: `TYPE_FP32` (or appropriate)
  - `shape`: `[BATCH, ...]`
  - **Description:** What this tensor represents.

## Example WebSocket payload (`/ws`)

### Request

```json
{
  "uuid": "example-client-uuid",
  "type": "inference",
  "payload": {
    "vm_id": "openstack-vm-id",
    "container_id": "docker-container-id",
    "model_name": "MODEL_NAME",
    "inputs": [
      {
        "name": "INPUT_NAME",
        "shape": [/* ... */],
        "datatype": "FP32",
        "data": [/* ... */]
      }
    ],
    "request": {
      "protocol": "http"
    }
  }
}
```

### Response (simplified)

```json
{
  "type": "inference_response",
  "payload": {
    "model_name": "MODEL_NAME",
    "outputs": [
      {
        "name": "OUTPUT_NAME",
        "shape": [/* ... */],
        "datatype": "FP32",
        "data": [/* ... */]
      }
    ]
  }
}
```

## Notes

- Keep this card in sync with `config.pbtxt` and the actual model graph.
- Document any important assumptions (normalisation, tokenisation, etc.).

