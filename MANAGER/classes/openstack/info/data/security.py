from dataclasses import dataclass
from typing import Optional

@dataclass
class Security:
    # --- Identity ---
    id: str
    name: str
    tenant_id: str
    project_id: str
    
    # --- Time ---
    created_at: Optional[str]
    updated_at: Optional[str]

    @classmethod
    def from_api(cls, data: dict) -> dict[str, "Security"]:
        securities: dict[str, Security] = {}

        for raw in data.get("security_groups",[]):
            needed = {
                
                # --- Identity ---
                "id":         raw["id"],
                "name":       raw["name"],
                "tenant_id":  raw["tenant_id"],
                "project_id": raw["project_id"],
                "created_at": raw["created_at"],
                "updated_at": raw["updated_at"]
            }

            securities[needed["name"]] = cls(**needed) # <------------------------- Changed from ID, better to use NAME for creation

        return securities
