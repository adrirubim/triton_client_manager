STATIC_START = "[OpenstackThread] "


class OpenstackCreationMissingKey(Exception):
    def __init__(self, key: str):
        self.key = key
        super().__init__(f"{STATIC_START}: {key} Missing !")


class OpenstackResourceNotFound(Exception):
    def __init__(self, resource_type: str, resource_value: str):
        self.resource_type = resource_type
        self.resource_value = resource_value
        super().__init__(f"{STATIC_START}{resource_type} not found: '{resource_value}'")


class OpenstackVMStateChanged(Exception):
    def __init__(self, vm_id: str, vm_name: str, changed_fields: list[str]):
        self.vm_id = vm_id
        self.vm_name = vm_name
        self.changed_fields = changed_fields
        super().__init__(f"{STATIC_START}VM '{vm_name}' ({vm_id}) state changed: {', '.join(changed_fields)}")


class OpenstackMissingArgument(Exception):
    def __init__(self, field: str):
        self.field = field
        super().__init__(f"{STATIC_START}Missing required argument: '{field}'")


class OpenstackDeletionMissingVM(Exception):
    def __init__(self, vm_id: str):
        self.vm_id = vm_id
        super().__init__(f"{STATIC_START}VM not found during deletion: '{vm_id}'")


class OpenstackDeletionError(Exception):
    def __init__(self, reason, vm_id: str):
        self.vm_id = vm_id
        super().__init__(f"{STATIC_START}Deletion error for VM '{vm_id}': {reason}")


class OpenstackDeletionTimeout(Exception):
    def __init__(self, vm_id: str):
        self.vm_id = vm_id
        super().__init__(f"{STATIC_START}Timed out waiting for VM deletion: '{vm_id}'")
