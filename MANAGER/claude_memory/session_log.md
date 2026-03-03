# Session Log

## 2026-02-25
- Executed refactor: `management.py` → thin dispatcher + `creation/` + `deletion/` subpackages
- `JobManagement` now exposes 9 individually callable actions via `getattr` dispatch (unchanged)
- `JobCreation` / `JobDeletion` own the sub-handlers; `management.py` aliases them for direct calls
- `jobs.yaml` `management_actions_available` expanded to all 9 actions
- Added payload examples for all new individual-step actions in `payload_examples/`
- Note: pre-existing bug in `classes/openstack/info/data/flavor.py` (bad dataclass field order) prevents full import-chain check; all new files syntax-checked clean

## 2026-02-24
- Created `claude_memory/` folder to persist context across sessions.
- Project: triton_client_manager/MANAGER
- Branch: master
- Fixed `model_name` extraction from `config.pbtxt` and removed docker.name dependency:
  - `create_docker`: generates UUID container name if `docker.name` is missing
  - `model_config.py` `process_config`: removed `folder_name` param; path is now `{folder}/{last_segment}/config.pbtxt` (last segment of folder repeated)
  - `management.py` `load_model`: removed `docker_config` param entirely; model_name 100% from pbtxt; raises TritonModelLoadFailed if no model_name resolved
- Fixed `model_name` extraction from `config.pbtxt` across 3 files:
  - `config_to_json.py`: added `model_name = cfg_dict.get("name")` + print for testing → confirmed returns 'example'
  - `classes/triton/model_config.py`: `_pbtxt_to_config` now returns 4-tuple (config_json, inputs, outputs, model_name); `process_config` renamed param to `folder_name`, returns same 4-tuple
  - `classes/job/management/management.py`: `load_model` now uses `folder_name` (docker_config.name) only for MinIO path; actual model_name for Triton API calls comes from pbtxt 'name' field, falls back to folder_name if minio not present
