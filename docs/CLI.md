## Triton Client Manager CLI (`tcm`)

This document describes the unified CLI entrypoint for Triton Client Manager.
The CLI is implemented in `apps/manager/tcm_cli.py`.

> Note: This repository also ships a separate, minimal SDK CLI (`tcm-client-cli`)
> under `sdk/src/tcm_client/cli.py`. That CLI is for integrators testing the
> WebSocket API from the SDK package and is **not** the same as the manager CLI
> documented here (`tcm ...` groups like `manager/config/model`).

> Note: This project is a monorepo. The recommended venv location is the **repo root**
> (`.venv/`). Avoid keeping a second active venv under `apps/manager/.venv` to prevent
> dependency drift.

---

### Installation / Environment

```bash
# From repository root
cd /var/www/triton_client_manager
python3 -m venv .venv
source .venv/bin/activate
pip install -r apps/manager/requirements.txt

# Optional (recommended): install the CLI entrypoint `tcm`
# This repo defines `tcm = apps.manager.tcm_cli:main` in apps/manager/pyproject.toml
pip install -e ./apps/manager
```

You can then invoke the CLI as:

```bash
# From repository root:
./.venv/bin/tcm --help

# Or, without installing the script:
./.venv/bin/python3 apps/manager/tcm_cli.py --help
```

Or if you are already inside `apps/manager`:

```bash
# From apps/manager:
../.venv/bin/tcm --help
../.venv/bin/python3 tcm_cli.py --help
```

---

### Command Groups

The CLI groups commands under three main namespaces:

- `tcm manager ...` – runtime and test orchestration for the manager.
- `tcm config ...` – configuration validation.
- `tcm model ...` – Triton model repository tooling (scaffold, analysis, pipelines, validation).

In code, you currently execute them via:

```bash
# From repository root:
./.venv/bin/tcm <group> <command> [options...]

# Or:
./.venv/bin/python3 apps/manager/tcm_cli.py <group> <command> [options...]
```

---

### `tcm manager` commands

#### `tcm manager dev`

Start the manager in development mode using `apps/manager/dev_server.py`.

```bash
tcm manager dev
```

Options:

- `--dry-run` – print the Python command that would be executed without running it.

#### `tcm manager test`

Run the manager test suite (via `pytest` in `apps/manager`):

```bash
tcm manager test
```

Options:

- `--dry-run` – print the `pytest` command that would be executed without running it.

---

### `tcm config` commands

#### `tcm config validate`

Validate all YAML files under `apps/manager/config/` against **Pydantic
schemas** defined in `apps/manager/config_schema.py`.

```bash
tcm config validate
```

Options:

- `--base-dir PATH` – base directory containing `config/` (default: `apps/manager`).
- `--dry-run` – print which files and schemas would be used without executing validation.

---

### `tcm model` commands

#### `tcm model scaffold`

Create a Triton model repository structure under `infra/models/{NAME}` from
an existing weights file (`.onnx` or `.safetensors`).

```bash
tcm model scaffold \
  --name YOLO_TEST \
  --format onnx \
  --path /tmp/model.onnx
```

This generates:

```text
infra/models/YOLO_TEST/
  config.pbtxt
  1/
    weights/
      model.onnx
```

The `config.pbtxt` file is generated using the Pydantic schemas in
`apps/manager/schemas/triton_model_config.py`. You can later refine `inputs`,
`outputs`, and `max_batch_size` manually or via future automation.

> Note (safetensors): Triton has no native `safetensors` backend. When you run
> `tcm model scaffold --format safetensors`, the scaffold uses the **Python
> backend** (`platform: "python"`) and writes a placeholder `infra/models/{NAME}/1/model.py`
> that must be implemented before it can serve inference.

#### `tcm model analyze`

Analyze a model artifact (local path or `s3://...`) and print a typed JSON report with
inspection results and a generated Triton `config.pbtxt` skeleton:

```bash
tcm model analyze --miniopath s3://bucket/path/model.onnx --name MYMODEL --category ML
```

Output shape (high-level):

- `inspection`: unified Schema v2 (format, size, IO, modalities, issues)
- `triton_config_pbtxt`: generated `config.pbtxt` text (static, infra-free)

Example output (simplified):

```json
{
  "inspection": {
    "format": "gguf",
    "size_bytes": 12345678,
    "io_info": {
      "inputs": [
        {"name": "prompt", "dtype": "BYTES", "shape": [-1]}
      ],
      "outputs": [
        {"name": "text", "dtype": "BYTES", "shape": [-1]}
      ]
    },
    "supported_modalities": ["text"],
    "issues": [
      {
        "level": "warning",
        "message": "GGUF inspection is KV-metadata only; weights are not loaded and deep tensor IO cannot be safely inferred.",
        "code": null,
        "source": "AnalyzeModelV2Action"
      },
      {
        "level": "warning",
        "message": "GGUF does not map to a native Triton backend; generated Python backend skeleton IO (prompt/text as TYPE_BYTES).",
        "code": "TRITON_GGUF_PYTHON_SKELETON",
        "source": "TritonConfigBridge"
      }
    ]
  },
  "triton_config_pbtxt": "name: \"MYMODEL\"\\nbackend: \"python\"\\nmax_batch_size: 0\\ninput [\\n  { name: \"prompt\" data_type: TYPE_BYTES dims: [ -1 ] }\\n]\\noutput [\\n  { name: \"text\" data_type: TYPE_BYTES dims: [ -1 ] }\\n]\\n"
}
```

#### `tcm model pipeline`

Generate a basic Triton ensemble pipeline for an existing model, scaffolding helper
steps (MinIO download, bytes→uint8, upload):

```bash
tcm model pipeline --name YOLO_TEST
```

This creates `infra/models/YOLO_TEST_PIPELINE/config.pbtxt` wiring:

- `MINIO_DOWNLOAD_IMG_TO_BYTES`
- `BYTES_TO_UINT8`
- `YOLO_TEST`
- `MINIO_UPLOAD_IMG_BYTES`

> Note: In this repository, these helper models pass raw objects as `TYPE_UINT8`
> tensors (byte arrays). They do not use Triton `TYPE_BYTES` for binary payloads.
>
> Additional pipeline tensors you may see in the ensemble graph:
> - `IMG_ORIGINAL`: the original object bytes (as `TYPE_UINT8`) propagated through the pipeline.
> - `MODEL_OUT`: the raw output tensor from the underlying model (shape/type depend on the model’s `config.pbtxt`).

#### `tcm model validate`

Run an end‑to‑end smoke test to ensure a model is deployed and responding
correctly:

```bash
tcm model validate --name YOLO_TEST --vm-id vm-1 --vm-ip 192.0.2.10 --container-id cont-1 --ws-uri ws://127.0.0.1:8000/ws
```

This wraps `ValidateModelAction` and reports whether:

- The Triton healthcheck `/v2/health/ready` succeeds (Triton is started via `infra/triton/docker-compose.yml` and is reachable at `http://localhost:8001` by default).
- A minimal inference via the manager returns without errors and matches Triton metadata.
  If routing fails with a missing `vm_ip`, pass `--vm-ip` explicitly.

