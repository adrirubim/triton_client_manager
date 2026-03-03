# Notes

## Project Structure
- `client_manager.py` — main entry point
- `classes/` — core classes
- `config/` — configuration files
- `utils/` — utilities
- `tests/` — smoke and regression tests
- `_______WEBSOCKET/` — websocket-related code
- `___openstack___/` — openstack-related code
- `payload_examples/` — example payloads

## Gotchas & Important Notes
- `docker.name` in the payload = folder name used to locate `config.pbtxt` in MinIO (NOT the Triton model name)
- Actual Triton model name = `name` field inside `config.pbtxt` (e.g. `name: "example"`)
- These two can differ. Always use pbtxt name for Triton API calls; use docker.name only for the S3 path.
- Triton ports: HTTP=8000 (single-shot ML), gRPC=8001 (streaming LLM), Metrics=8002
- Model repo path in MinIO: `{folder}/{docker.name}/config.pbtxt`

## Needed / 
- Test the full creation flow end-to-end with a real MinIO + Triton setup
- Verify inference pipeline (TritonInfer) works after model load returns correct model_name + inputs/outputs
