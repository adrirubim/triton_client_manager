from dataclasses import dataclass
from typing import Optional

@dataclass
class Network:
    # --- Identity ---
    id: str
    name: str
    tenant_id: str
    project_id: str

    # --- Info ---
    shared: bool
    status: str
    subnets: list[str]
    router_internal: Optional[bool] = False
    router_external: Optional[bool] = False

    # --- Time ---
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_api(cls, data: dict) -> dict[str, "Network"]:
        networks: dict[str, Network] = {}

        for raw in data.get("networks", []):
            needed = {
                # --- Identity ---
                "id": raw["id"],
                "name": raw["name"],
                "tenant_id": raw["tenant_id"],
                "project_id": raw["project_id"],

                # --- Info ---
                "shared": raw["shared"],
                "status": raw["status"],
                "subnets": raw.get("subnets", []),
                "router_internal": raw.get("router:internal", False),
                "router_external": raw.get("router:external", False),

                # --- Time ---
                "created_at": raw.get("created_at"),
                "updated_at": raw.get("updated_at"),
            }

            networks[needed["id"]] = cls(**needed)

        return networks
