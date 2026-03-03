from dataclasses import dataclass


@dataclass
class Host:
    # --- Identity ---
    id: str  # id (UUID with microversion 2.53)
    name: str  # hypervisor_hostname
    architecture: str  # cpu_info.arch

    # --- Info ---
    vcpus: int
    vcpus_used: int

    memory_mb: int
    memory_mb_used: int
    memory_mb_free: int

    local_gb: int
    local_gb_used: int
    local_gb_free: int

    # --- Status ---
    state: str
    status: str
    running_vms: int

    @classmethod
    def from_api(cls, data: dict) -> dict[str, "Host"]:
        hosts: dict[str, Host] = {}

        for raw in data["hypervisors"]:
            needed = {
                # --- Identity ---
                "id": raw["id"],
                "name": raw["hypervisor_hostname"],
                "architecture": raw["cpu_info"]["arch"],
                # --- Info ---
                "vcpus": raw["vcpus"],
                "vcpus_used": raw["vcpus_used"],
                "memory_mb": raw["memory_mb"],
                "memory_mb_used": raw["memory_mb_used"],
                "memory_mb_free": raw["free_ram_mb"],
                "local_gb": raw["local_gb"],
                "local_gb_used": raw["local_gb_used"],
                "local_gb_free": raw["free_disk_gb"],
                # --- Status ---
                "state": raw["state"],
                "status": raw["status"],
                "running_vms": raw["running_vms"],
            }

            hosts[needed["id"]] = cls(**needed)

        return hosts
