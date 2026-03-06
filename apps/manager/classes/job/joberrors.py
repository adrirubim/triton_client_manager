class JobActionNotFound(Exception):
    def __init__(self, action: str):
        self.action = action
        super().__init__(f"Job action not found: {action!r}")


class JobVMCreationFailed(Exception):
    def __init__(self, reason: str = "Unknown"):
        self.reason = reason
        super().__init__(f"VM creation failed: {reason}")


class JobContainerCreationFailed(Exception):
    def __init__(self, reason: str = "Unknown"):
        self.reason = reason
        super().__init__(f"Container creation failed: {reason}")


class JobDeletionMissingField(Exception):
    def __init__(self, field: str):
        self.field = field
        super().__init__(f"Deletion missing required field: {field!r}")


class JobDeletionFailed(Exception):
    def __init__(self, reason: str = "Unknown"):
        self.reason = reason
        super().__init__(f"Deletion failed: {reason}")


class JobInferenceMissingField(Exception):
    def __init__(self, field: str):
        self.field = field
        super().__init__(f"Inference missing required field: {field!r}")
