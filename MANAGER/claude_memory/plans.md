# Plans

## Active

### [PENDING DISCUSSION] Refactor JobInference + Auto-detect Port from config.pbtxt
Plan file: `/home/marco/.claude/plans/wise-orbiting-deer.md`

**Core idea:** `config.pbtxt` contains `model_transaction_policy { decoupled: true }` for gRPC-streaming models. Detect it at parse time → return `port` (8001=gRPC / 8000=HTTP) from `process_config` → propagate through creation response → client sends `port` in inference payload → handler routes to the right TritonInfer method.

**Scope of changes:**
1. `classes/triton/model_config.py` — detect `decoupled`, add `port` to 5-tuple return
2. `classes/job/management/creation/model.py` — unpack new 5-tuple, expose `port`
3. `classes/job/management/creation/creation.py` — add `port` to result dict
4. `classes/job/inference/inference.py` — refactor to thin dispatcher
5. New `classes/job/inference/handlers/` — `base.py`, `llm.py`, `ml.py`
6. Payload examples updated

**Status:** Pending design discussion on inference routing logic

## Completed

### [DONE 2026-02-25] Refactor JobManagement + Individual Pipeline Actions

**Goal:** Break `management.py` into per-step handler classes AND expose each step as an individually callable action.

**Structure delivered:**
```
management/
├── management.py           — thin dispatcher, all actions as methods
├── creation/
│   ├── creation.py         — JobCreation (full pipeline, calls 3 sub-handlers)
│   ├── vm.py               — JobCreateVM
│   ├── container.py        — JobCreateContainer
│   └── model.py            — JobLoadModel + inspect_config()
└── deletion/
    ├── deletion.py         — JobDeletion (full teardown)
    ├── vm.py               — JobDeleteVM
    ├── container.py        — JobDeleteContainer
    └── model.py            — JobUnloadModel
```

**Actions in jobs.yaml:**
`creation, deletion, create_vm, create_container, load_model, inspect_config, unload_model, delete_container, delete_vm`

**Payload convention:** `vm_ip` always under `openstack.vm_ip` for individual step actions.
**Full creation** reuses same sub-handlers via `job_creation._vm`, `_container`, `_model`.
**Payload examples** added in `payload_examples/` for all 9 actions.
