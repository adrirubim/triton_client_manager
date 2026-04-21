from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.docker import DockerThread

from classes.triton.constants import TYPE_MAP
from classes.triton.tritonerrors import TritonInferenceFailed


def check_instance(docker: "DockerThread", vm_ip: str, container_id: str) -> None:
    # In development mode we may run with a Docker stub that doesn't maintain
    # container state. In that case, instance validation is a no-op and routing
    # relies on the explicit vm_ip/container_id provided by the caller.
    try:
        dict_containers = docker.dict_containers
    except Exception:
        return

    container = dict_containers.get(container_id)
    if container is None:
        raise ValueError(f"Container '{container_id[:12]}' not found in known containers")
    if container.worker_ip != vm_ip:
        raise ValueError(f"Container '{container_id[:12]}' is not on VM '{vm_ip}' (found on '{container.worker_ip}')")


def _normalize_triton_inputs(inputs: object) -> list:
    """
    Normalize inference inputs to the internal manager shape used by `classes.triton.infer`:

    - Internal (manager) format: {name, dims, type, value}
    - SDK (tcm-client) format:   {name, shape, datatype, data}
    """
    if not isinstance(inputs, list):
        return []

    # If the caller passes a non-dict list (e.g. tests, or future extensions),
    # preserve it as-is instead of accidentally erasing it to [].
    if any(not isinstance(item, dict) for item in inputs):
        return inputs

    normalized: list = []
    for item in inputs:
        # Preferred internal shape
        if {"name", "dims", "type", "value"}.issubset(item.keys()):
            normalized.append(item)
            continue

        # SDK-friendly shape (tcm-client)
        if {"name", "shape", "datatype", "data"}.issubset(item.keys()):
            normalized.append(
                {
                    "name": item.get("name"),
                    "dims": item.get("shape"),
                    "type": item.get("datatype"),
                    "value": item.get("data"),
                }
            )
            continue

        # Unknown/partial shapes: keep as-is so downstream can error clearly
        normalized.append(item)

    return normalized


def normalize_inference_payload(payload: dict, docker: "DockerThread") -> dict:
    """
    Best-effort backwards compatibility normalizer for inference payloads.

    Current runtime handlers validate against:
      - payload.vm_ip
      - payload.container_id
      - payload.model_name
      - payload.request.inputs

    But docs/payload examples/SDK may send:
      - payload.inputs (top-level)
      - payload.vm_id (and omit vm_ip)
      - SDK-style input dicts (shape/datatype/data)
    """
    if not isinstance(payload, dict):
        return {}

    # Ensure `request` exists.
    request = payload.get("request")
    if not isinstance(request, dict):
        request = {}
        payload["request"] = request

    # Accept legacy top-level `inputs` by mapping to request.inputs.
    if "inputs" in payload and "inputs" not in request:
        request["inputs"] = payload.get("inputs")

    # Normalize input shapes (both request.inputs and pipeline step inputs).
    if "inputs" in request:
        request["inputs"] = _normalize_triton_inputs(request.get("inputs"))

    # If vm_ip is missing but container_id is present, derive vm_ip from Docker cache
    # when DockerThread is available.
    if not payload.get("vm_ip"):
        container_id = payload.get("container_id")
        if isinstance(container_id, str) and container_id:
            try:
                dict_containers = docker.dict_containers
            except Exception:
                dict_containers = None

            if dict_containers is not None:
                container = dict_containers.get(container_id)
                if container is not None and getattr(container, "worker_ip", None):
                    payload["vm_ip"] = container.worker_ip

    return payload


def validate_fields(payload: dict) -> tuple:
    """Returns (vm_ip, container_id, model_name, inputs). Raises ValueError if any missing."""
    vm_ip = payload.get("vm_ip")
    container_id = payload.get("container_id")
    model_name = payload.get("model_name")
    request = payload.get("request")
    if not isinstance(request, dict) or "inputs" not in request:
        raise ValueError("Missing required field 'request.inputs'")
    inputs = request.get("inputs", [])

    if not vm_ip:
        raise ValueError("Missing required field 'vm_ip'")
    if not container_id:
        raise ValueError("Missing required field 'container_id'")
    if not model_name:
        raise ValueError("Missing required field 'model_name'")

    return vm_ip, container_id, model_name, inputs


def _dtype_size_bytes(datatype: str) -> int:
    dt = str(TYPE_MAP.get(datatype, datatype) or "").upper()
    if dt in {"BOOL", "INT8", "UINT8"}:
        return 1
    if dt in {"INT16", "UINT16", "FP16"}:
        return 2
    if dt in {"INT32", "UINT32", "FP32"}:
        return 4
    if dt in {"INT64", "UINT64", "FP64"}:
        return 8
    if dt in {"BYTES"}:
        # Conservative baseline per element (pointer-ish + overhead).
        return 8
    return 4


def _numel(dims: object) -> int:
    if isinstance(dims, int):
        return max(0, int(dims))
    if isinstance(dims, (list, tuple)):
        n = 1
        for d in dims:
            try:
                di = int(d)
            except Exception:
                return 0
            if di < 0:
                return 0
            n *= max(1, di)
        return int(n)
    return 0


def estimate_payload_bytes(inputs: object) -> int:
    """
    Best-effort decoded tensor payload estimate.

    This is intentionally fast and does not walk BYTES contents.
    """
    if not isinstance(inputs, list):
        return 0
    total = 0
    for inp in inputs:
        if not isinstance(inp, dict):
            continue
        dims = inp.get("dims")
        datatype = inp.get("type")
        total += _numel(dims) * _dtype_size_bytes(str(datatype or ""))
    return int(max(0, total))


def enforce_payload_budget(model_name: str, inputs: object, *, max_request_payload_mb: int) -> None:
    if not max_request_payload_mb:
        return
    limit = int(max(0, max_request_payload_mb)) * 1024 * 1024
    est = estimate_payload_bytes(inputs)
    if est > limit:
        raise TritonInferenceFailed(
            model_name,
            f"413 Payload Too Large: estimated_bytes={est} limit_bytes={limit}",
        )
