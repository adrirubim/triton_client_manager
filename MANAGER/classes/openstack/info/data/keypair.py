from dataclasses import dataclass
from typing import Optional

@dataclass
class Keypair:
    # --- Identity ---
    name: str    
    type: str
    fingerprint: str         

    @classmethod
    def from_api(cls, data: dict) -> dict[str, "Keypair"]:
        keypairs: dict[str, Keypair] = {}

        for raw in data.get("keypairs",[]):
            raw_key = raw["keypair"]
            needed = {
                
                # --- Identity ---
                "name":        raw_key["name"],
                "type":        raw_key["type"],
                "fingerprint": raw_key["fingerprint"]
            }

            keypairs[needed["name"]] = cls(**needed)

        return keypairs
