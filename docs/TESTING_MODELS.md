## Testing Triton Models (Smoke Flow)

This document describes the **smoke test** flow used to validate that a Triton
model generated with `tcm model scaffold` is correctly deployed and responding
before promoting it to higher environments.

---

### 1. Prepare the Triton model

1. Generate the model structure from a weights file (`.onnx`):

   ```bash
   cd /var/www/triton_client_manager
   touch /tmp/dummy.onnx  # replace with your real model
   export PYTHONPATH=$(pwd):$(pwd)/src
   source .venv/bin/activate
   python3 apps/manager/tcm_cli.py model scaffold \
     --name YOLO_TEST \
     --format onnx \
     --path /tmp/dummy.onnx
   ```

2. Verify the generated structure:

   ```bash
   ls -R infra/models/YOLO_TEST
   cat infra/models/YOLO_TEST/config.pbtxt
   ```

   You should see:

   - `infra/models/YOLO_TEST/config.pbtxt`
   - `infra/models/YOLO_TEST/1/weights/model.onnx` (generated locally by the scaffold step; not necessarily committed in this repository)

---

### 2. Start Triton with `docker-compose`

The repository includes a minimal Triton definition in
`infra/triton/docker-compose.yml` that mounts `infra/models/` as the
`model-repository`.

To start Triton ephemerally:

```bash
cd /var/www/triton_client_manager
docker compose -f infra/triton/docker-compose.yml up -d
```

This will:

- pull the `nvcr.io/nvidia/tritonserver:26.03-py3` image (first run),
- start the `tcm-triton-ephemeral` container,
- expose Triton HTTP on port `8001` of the host.

To stop and clean up:

```bash
docker compose -f infra/triton/docker-compose.yml down
```

---

### 3. Validate the model with `tcm model validate`

The `tcm model validate` command automates the validation flow:

1. starts Triton temporarily using `docker-compose`,
2. runs a minimal inference via the internal SDK (`tcm_client`) against the
   manager (WebSocket `/ws`),
3. verifies that the response contains no errors.

Example run:

```bash
cd /var/www/triton_client_manager
export PYTHONPATH=$(pwd):$(pwd)/src:$(pwd)/sdk/src
source .venv/bin/activate
python3 apps/manager/tcm_cli.py model validate --name YOLO_TEST
```

Expected output (simplified):

- `docker compose` logs for bringing Triton up/down,
- final message in the console:

```text
Model 'YOLO_TEST' validated successfully ✅
```

If anything goes wrong (for example, Triton is not reachable or the response
contract is not as expected), the command will raise an exception and return a
non‑zero exit code, which can be used by CI/CD to block model promotion.

---

### 4. Summary

- `tcm model scaffold` generates the standard structure under `infra/models/{name}`.
- `docker compose -f infra/triton/docker-compose.yml up -d` starts a temporary
  Triton instance pointing at that model repository.
- `tcm model validate --name NAME` runs the Triton **smoke test** end‑to‑end
  using the internal SDK and validates that the model responds correctly.

