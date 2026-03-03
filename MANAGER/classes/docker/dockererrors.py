STATIC_START = "[DockerThread] "


class DockerCreationMissingField(Exception):
    def __init__(self, field: str):
        self.field = field
        super().__init__(f"{STATIC_START}: {field} Missing !")


class DockerImageNotFound(Exception):
    def __init__(self, image: str):
        self.image = image
        super().__init__(f"{STATIC_START}Image not found: '{image}'")


class DockerAPIError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"{STATIC_START}Docker API error: {reason}")


class DockerContainerStateChanged(Exception):
    def __init__(
        self, container_id: str, container_name: str, worker_ip: str, changed_fields: list[str]
    ):
        self.container_id = container_id
        self.container_name = container_name
        self.worker_ip = worker_ip
        self.changed_fields = changed_fields
        super().__init__(
            f"{STATIC_START}Container '{container_name}' ({container_id[:12]}) on {worker_ip} state changed: {', '.join(changed_fields)}"
        )


class DockerMissingArgument(Exception):
    def __init__(self, field: str):
        self.field = field
        super().__init__(f"{STATIC_START}Missing required argument: '{field}'")


class DockerMissingContainer(Exception):
    def __init__(self, container_id: str):
        self.container_id = container_id
        super().__init__(f"{STATIC_START}Container not found: '{container_id}'")


class DockerDeletionError(Exception):
    def __init__(self, reason):
        super().__init__(f"{STATIC_START}Deletion error: {reason}")
