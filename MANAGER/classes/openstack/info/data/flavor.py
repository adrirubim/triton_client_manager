from dataclasses import dataclass
from typing import Optional


@dataclass
class Flavor:
    # --- Identity ---
    id: str               # id (UUID with microversion 2.53)
    name: str             

    # --- Info ---
    vcpus: int
    local_gb: int
    memory_mb: int
    swap: Optional[int] = None

    @classmethod
    def from_api(cls, data: dict) -> dict[str, "Flavor"]:
        flavors: dict[str, Flavor] = {}

        for raw in flavors["flavors"]:
            needed = {
                
                # --- Identity ---
                "id": raw["id"],
                "name": raw["name"],

                # --- Info ---
                "swap": raw.get("swap", None),
                "vcpus": raw["vcpus"],
                "local_gb": raw["disk"],
                "memory_mb": raw["ram"]
            }

            flavors[needed["id"]] = cls(**needed)

        return flavors
