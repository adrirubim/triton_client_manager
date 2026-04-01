# YOLO_N_INT8 – Model Card

## Purpose

Compact YOLO model quantized to INT8 for real‑time object detection on edge‑class
GPUs. Intended for low‑latency inference with moderate accuracy requirements.

## Format and Location

- **Format:** ONNX (INT8 quantized)
- **Repository path:** `infra/models/YOLO_N_INT8/`
- **Config file:** `infra/models/YOLO_N_INT8/config.pbtxt`
- **Weights:** `infra/models/YOLO_N_INT8/1/weights/model.onnx`

## Inputs / Outputs

> Note: This card documents the interface **as defined by**
> `infra/models/YOLO_N_INT8/config.pbtxt` in this repository.

### Inputs

- **`INPUT__0`**
  - `data_type`: `TYPE_FP32`
  - `shape`: `[1, 3, 224, 224]`
  - **Description:** Input tensor as exposed by the ONNX graph / Triton config.

### Outputs

- **`OUTPUT__0`**
  - `data_type`: `TYPE_FP32`
  - `shape`: `[1, 3, 224, 224]`
  - **Description:** Output tensor as exposed by the ONNX graph / Triton config.

## Example WebSocket payload (`/ws`)

### Request

```json
{
  "uuid": "example-client-uuid",
  "type": "inference",
  "payload": {
    "vm_id": "openstack-vm-id",
    "container_id": "docker-container-id",
    "model_name": "YOLO_N_INT8",
    "inputs": [
      {
          "name": "INPUT__0",
          "shape": [1, 3, 224, 224],
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
    "model_name": "YOLO_N_INT8",
    "outputs": [
      {
        "name": "OUTPUT__0",
        "shape": [1, 3, 224, 224],
        "datatype": "FP32",
        "data": [/* ... */]
      }
    ]
  }
}
```

## Notes

- If you want a human-friendly input name like `images` in client payloads,
  use an **ensemble** model (for example `YOLO_N_INT8_PIPELINE`) that maps
  friendly names to the underlying model’s `INPUT__0`.
- For production deployments, pair this model with the monitoring dashboards in
  `infra/monitoring/grafana/dashboard_omega.json` to track latency and error
  rates per model.

