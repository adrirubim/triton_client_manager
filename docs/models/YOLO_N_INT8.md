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

> Note: The exact shapes and dtypes must match the Triton `config.pbtxt` for
> this model; values below illustrate the expected structure.

### Inputs

- **`images`**
  - `data_type`: `TYPE_FP32`
  - `shape`: `[1, 3, 640, 640]`
  - **Description:** Batch of RGB images normalised to `[0, 1]`.

### Outputs

- **`boxes`**
  - `data_type`: `TYPE_FP32`
  - `shape`: `[1, N, 4]`
  - **Description:** Bounding boxes in `(x1, y1, x2, y2)` format.

- **`scores`**
  - `data_type`: `TYPE_FP32`
  - `shape`: `[1, N]`
  - **Description:** Confidence score per detection.

- **`labels`**
  - `data_type`: `TYPE_INT64`
  - `shape`: `[1, N]`
  - **Description:** Class index for each detection.

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
        "name": "images",
        "shape": [1, 3, 640, 640],
        "datatype": "FP32",
        "data": [
          0.0, 0.0, 0.0
          // ...
        ]
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
        "name": "boxes",
        "shape": [1, 10, 4],
        "datatype": "FP32",
        "data": [/* ... */]
      },
      {
        "name": "scores",
        "shape": [1, 10],
        "datatype": "FP32",
        "data": [/* ... */]
      },
      {
        "name": "labels",
        "shape": [1, 10],
        "datatype": "INT64",
        "data": [/* ... */]
      }
    ]
  }
}
```

## Notes

- Ensure that `config.pbtxt` and the ONNX graph use consistent names and shapes
  for all inputs and outputs defined above.
- For production deployments, pair this model with the monitoring dashboards in
  `infra/monitoring/grafana/dashboard_omega.json` to track latency and error
  rates per model.

