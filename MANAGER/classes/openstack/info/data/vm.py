from dataclasses import dataclass
from typing import Optional

@dataclass
class VM:
    # --- Identity ---
    id: str
    name: str
    status: str

    # --- Wtf? ---
    user_id: str
    project_id: str

    # --- Host ---
    host_id: str
    host_name: str

    # --- Specs ---
    image_id: str
    flavor_name: str

    # --- Network ---
    mac_public: Optional[str] = None
    mac_private: Optional[str] = None
    address_public: Optional[str] = None
    address_private: Optional[str] = None

    # --- Time ---
    created: str = ""
    launched: Optional[str] = None
    terminated: Optional[str] = None

    @staticmethod
    def _ipv4_mac(entries: Optional[list[dict]]) -> tuple[Optional[str], Optional[str]]:
        if not entries:
            return None, None

        for e in entries:
            if e.get("version") == 4 and e.get("addr"):
                return e.get("OS-EXT-IPS-MAC:mac_addr"), e.get("addr")

        return None, None
    
    @classmethod
    def _parse_raw(cls, raw: dict) -> dict:
        addresses: dict[str, list[dict]] = raw.get("addresses") or {}
        mac_public, address_public = cls._ipv4_mac(addresses.get("public"))
        mac_private, address_private = cls._ipv4_mac(addresses.get("private"))

        return {
            "id": raw["id"],
            "name": raw["name"],
            "status": raw["OS-EXT-STS:vm_state"],
            "user_id": raw["user_id"],
            "project_id": raw["tenant_id"],
            "host_id": raw["hostId"],
            "host_name": raw["OS-EXT-SRV-ATTR:hypervisor_hostname"],
            "image_id": raw["image"]["id"],
            "flavor_name": raw["flavor"]["original_name"],
            "mac_public": mac_public,
            "address_public": address_public,
            "mac_private": mac_private,
            "address_private": address_private,
            "created": raw["created"],
            "launched": raw.get("OS-SRV-USG:launched_at"),
            "terminated": raw.get("OS-SRV-USG:terminated_at"),
        }

    @classmethod
    def from_api(cls, data: dict) -> dict[str, "VM"]:
        vms: dict[str, VM] = {}
        for raw in data.get("servers", []):
            parsed = cls._parse_raw(raw)
            vms[parsed["id"]] = cls(**parsed)
        return vms
    
    @classmethod
    def from_id(cls, raw: dict) -> "VM":
        return cls(**cls._parse_raw(raw))
    
    def has_changed(self, other: "VM") -> tuple[bool, list[str]]:
        changed_fields = []
        
        if self.status != other.status:
            changed_fields.append(f"status: {other.status} -> {self.status}")
        
        if self.host_id != other.host_id:
            changed_fields.append(f"host_id: {other.host_id} -> {self.host_id}")
        
        if self.address_private != other.address_private:
            changed_fields.append(f"address_private: {other.address_private} -> {self.address_private}")
        
        return (len(changed_fields) > 0, changed_fields)
