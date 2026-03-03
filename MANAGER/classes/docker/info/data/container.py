import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Container:
    """Docker container from remote API"""
    # --- Identity ---
    id: str                    # Container ID (short or long)
    name: str                  # Container name
    image_name: str            # Image name (e.g., "tritonserver")
    image_tag: str             # Image tag (e.g., "24.01-py3")
    
    # --- Status ---
    status: str                # running, exited, paused, etc.
    state: str                 # State details
    
    # --- Location ---
    worker_ip: str             # Which VM it's running on
    
    # --- Network ---
    ports: Optional[dict] = None      # Port mappings
    
    # --- Time ---
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    
    @classmethod
    def _parse_raw(cls, data: dict, worker_ip: str) -> dict:
        container_id = data.get("Id", "")
        
        names = data.get("Names", [])
        container_name = names[0].lstrip('/') if names else container_id[:12]
        
        image_full = data.get("Image", "")
        if ':' in image_full:
            image_name, image_tag = image_full.rsplit(':', 1)
        else:
            image_name = image_full
            image_tag = "latest"
        
        status = data.get("Status", "")
        state = data.get("State", "")
        
        ports = data.get("Ports", [])
        port_mappings = {}
        for port in ports:
            if isinstance(port, dict):
                private_port = port.get("PrivatePort")
                public_port = port.get("PublicPort")
                port_type = port.get("Type", "tcp")
                if private_port:
                    key = f"{private_port}/{port_type}"
                    if public_port:
                        port_mappings[key] = public_port
                    else:
                        port_mappings[key] = None
        
        created_at = data.get("Created")
        started_at = data.get("StartedAt")
        
        return {
            "id": container_id,
            "name": container_name,
            "image_name": image_name,
            "image_tag": image_tag,
            "status": status,
            "state": state,
            "worker_ip": worker_ip,
            "ports": port_mappings if port_mappings else None,
            "created_at": str(created_at) if created_at else None,
            "started_at": str(started_at) if started_at else None
        }
    
    @classmethod
    def from_api(cls, data: list, worker_ip: str) -> dict[str, "Container"]:
        containers: dict[str, Container] = {}
        
        if not isinstance(data, list):
            return containers
        
        for container_data in data:
            try:
                container_id = container_data.get("Id", "")
                if not container_id:
                    continue
                
                parsed = cls._parse_raw(container_data, worker_ip)
                containers[container_id] = cls(**parsed)
                
            except Exception as e:
                logger.warning("Failed to parse container data: %s", e)
                continue
        
        return containers
    
    @classmethod
    def from_id(cls, data: dict, worker_ip: str) -> "Container":
        return cls(**cls._parse_raw(data, worker_ip))
    
    def has_changed(self, other: "Container") -> tuple[bool, list[str]]:
        changed_fields = []
        
        if self.state != other.state:
            changed_fields.append(f"state: {other.state} -> {self.state}")
        
        if self.status != other.status:
            changed_fields.append(f"status: {other.status} -> {self.status}")
        
        return (len(changed_fields) > 0, changed_fields)
