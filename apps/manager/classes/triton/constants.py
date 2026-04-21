###################################
#       Triton Constants          #
###################################

# Fixed ports used by every Triton container
HTTP_PORT = 8000  # HTTP  — health checks, load/unload, single-shot ML inference
GRPC_PORT = 8001  # gRPC  — streaming LLM inference

# Maps Triton model config types (TYPE_*) to tritonclient API datatypes
TYPE_MAP = {
    "TYPE_STRING": "BYTES",
    "TYPE_BOOL": "BOOL",
    "TYPE_UINT8": "UINT8",
    "TYPE_UINT16": "UINT16",
    "TYPE_UINT32": "UINT32",
    "TYPE_UINT64": "UINT64",
    "TYPE_INT8": "INT8",
    "TYPE_INT16": "INT16",
    "TYPE_INT32": "INT32",
    "TYPE_INT64": "INT64",
    "TYPE_FP16": "FP16",
    "TYPE_FP32": "FP32",
    "TYPE_FP64": "FP64",
}
