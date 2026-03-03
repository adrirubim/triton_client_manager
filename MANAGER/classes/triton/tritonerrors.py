STATIC_START = "[TritonThread] "

class TritonServerHealthFailed(Exception):
    def __init__(self, timeout: int):
        self.timeout = timeout
        super().__init__(f"{STATIC_START}Server failed to become ready within {timeout}s")

class TritonModelLoadFailed(Exception):
    def __init__(self, model_name: str, reason: str = "Unknown"):
        self.model_name = model_name
        self.reason = reason
        super().__init__(f"{STATIC_START}Model '{model_name}' load failed: {reason}")

class TritonModelNotReady(Exception):
    def __init__(self, model_name: str, timeout: int):
        self.model_name = model_name
        self.timeout = timeout
        super().__init__(f"{STATIC_START}Model '{model_name}' failed to become ready within {timeout}s")

class TritonConfigDownloadFailed(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"{STATIC_START}Failed to download model config from S3: {reason}")

class TritonInferenceFailed(Exception):
    def __init__(self, model_name: str, reason: str = "Unknown"):
        self.model_name = model_name
        self.reason = reason
        super().__init__(f"{STATIC_START}Inference failed for model '{model_name}': {reason}")

class TritonServerStateChanged(Exception):
    def __init__(self, vm_ip: str, container_id: str, changed_fields: list):
        self.vm_ip = vm_ip
        self.container_id = container_id
        self.changed_fields = changed_fields
        super().__init__(f"{STATIC_START}Server ({vm_ip}, {container_id[:12]}) state changed: {changed_fields}")

class TritonServerCreationFailed(Exception):
    def __init__(self, vm_ip: str, container_id: str, reason: str):
        self.vm_ip = vm_ip
        self.container_id = container_id
        self.reason = reason
        super().__init__(f"{STATIC_START}Server creation failed for ({vm_ip}, {container_id[:12]}): {reason}")

class TritonMissingArgument(Exception):
    def __init__(self, field: str):
        self.field = field
        super().__init__(f"{STATIC_START}Missing required argument: '{field}'")

class TritonMissingInstance(Exception):
    def __init__(self, vm_id: str, container_id: str):
        self.vm_id = vm_id
        self.container_id = container_id
        super().__init__(f"{STATIC_START}Server instance not found: vm_id='{vm_id}', container_id='{container_id}'")
