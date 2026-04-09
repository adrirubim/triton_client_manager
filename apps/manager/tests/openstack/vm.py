from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def pick(d: Dict[str, Any], *keys: str, default=None):
    """Return the first existing, non-None value for any of the keys."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def parse_dt(value: Any) -> Optional[str]:
    """Parse datetime and return ISO 8601 string (JSON-serializable for PHP)."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if isinstance(value, str):
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(v)
            dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            return None
    return None


@dataclass
class Identity:
    id: str
    name: str
    image_id: Optional[str]
    project_id: Optional[str]
    user_id: Optional[str]
    zone: Optional[str]
    host: Optional[str]


@dataclass
class Flavor:
    name: Optional[str]
    cpu: Optional[float]
    ram: Optional[int]
    disk: Optional[float]
    extra_specs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Networking:
    network: str
    address_type: int  # 4 or 6
    address: str
    mac: Optional[str]


@dataclass
class Access:
    key_name: Optional[str]
    config_drive: Optional[bool]
    security_groups: List[str] = field(default_factory=list)


@dataclass
class Timestamps:
    created: Optional[str]  # ISO 8601 string
    updated: Optional[str]  # ISO 8601 string
    launched: Optional[str]  # ISO 8601 string
    terminated: Optional[str]  # ISO 8601 string


@dataclass
class State:
    status: Optional[str]
    power_state: Optional[int]
    task_state: Optional[str]
    progress: Optional[int]
    host_status: Optional[str]
    locked: Optional[str]  # None if unlocked, reason string if locked
    volumes_attached: List[Any] = field(default_factory=list)


@dataclass
class VM:
    identity: Identity
    flavor: Flavor
    networking: List[Networking]
    timestamps: Timestamps
    access: Access
    state: State

    @staticmethod
    def from_server(s: Any) -> "VM":
        d = s.to_dict()  # <- important: normalized keys are visible here

        # Image id
        image = d.get("image")
        image_id = image.get("id") if isinstance(image, dict) else None

        # Zone / host - try direct attribute access first, then dict lookup
        # Use hypervisor_hostname for the actual host machine name
        zone = getattr(s, "availability_zone", None) or pick(
            d, "OS-EXT-AZ:availability_zone", "OS_EXT_AZ_availability_zone"
        )
        host = (
            getattr(s, "hypervisor_hostname", None)
            or pick(
                d,
                "OS-EXT-SRV-ATTR:hypervisor_hostname",
                "OS_EXT_SRV_ATTR_hypervisor_hostname",
            )
            or getattr(s, "host", None)
            or pick(d, "OS-EXT-SRV-ATTR:host", "OS_EXT_SRV_ATTR_host")
        )

        identity = Identity(
            id=str(pick(d, "id", default="")),
            name=str(pick(d, "name", default="")),
            image_id=image_id,
            project_id=pick(d, "tenant_id", "project_id"),
            user_id=pick(d, "user_id"),
            zone=zone,
            host=host,
        )

        # Flavor
        flav = d.get("flavor")
        if isinstance(flav, dict):
            flavor_name = flav.get("original_name") or flav.get("name")
            cpu = flav.get("vcpus")
            ram = flav.get("ram")
            disk = flav.get("disk")
            extra_specs = flav.get("extra_specs") or {}
        else:
            flavor_name = str(flav) if flav else None
            cpu = ram = disk = None
            extra_specs = {}

        flavor = Flavor(
            name=flavor_name,
            cpu=float(cpu) if cpu is not None else None,
            ram=int(ram) if ram is not None else None,
            disk=float(disk) if disk is not None else None,
            extra_specs=dict(extra_specs) if isinstance(extra_specs, dict) else {},
        )

        # Networking
        nets: List[Networking] = []
        addresses = d.get("addresses") or {}
        if isinstance(addresses, dict):
            for net_name, addr_list in addresses.items():
                if not isinstance(addr_list, list):
                    continue
                for a in addr_list:
                    if not isinstance(a, dict):
                        continue
                    ver = a.get("version")
                    ip = a.get("addr")
                    mac = a.get("OS-EXT-IPS-MAC:mac_addr")
                    if ver in (4, 6) and ip:
                        nets.append(
                            Networking(
                                network=str(net_name),
                                address_type=int(ver),
                                address=str(ip),
                                mac=str(mac) if mac else None,
                            )
                        )

        # Access
        sec_groups_raw = d.get("security_groups") or []
        sec_groups: List[str] = []
        if isinstance(sec_groups_raw, list):
            for g in sec_groups_raw:
                if isinstance(g, dict) and "name" in g:
                    sec_groups.append(str(g["name"]))
                elif isinstance(g, str):
                    sec_groups.append(g)

        # Handle config_drive - convert empty string to False
        config_drive_raw = pick(d, "config_drive")
        config_drive = bool(config_drive_raw) if config_drive_raw != "" else False

        access = Access(
            key_name=pick(d, "key_name"),
            config_drive=config_drive,
            security_groups=sec_groups,
        )

        # Timestamps (try both naming styles)
        timestamps = Timestamps(
            created=parse_dt(pick(d, "created", "created_at")),
            updated=parse_dt(pick(d, "updated", "updated_at")),
            launched=parse_dt(pick(d, "OS-SRV-USG:launched_at", "OS_SRV_USG_launched_at", "launched_at")),
            terminated=parse_dt(
                pick(
                    d,
                    "OS-SRV-USG:terminated_at",
                    "OS_SRV_USG_terminated_at",
                    "terminated_at",
                )
            ),
        )

        # State - try direct attribute access first for OpenStack extension fields
        volumes_attached = (
            pick(
                d,
                "os-extended-volumes:volumes_attached",
                "os_extended_volumes_volumes_attached",
                default=[],
            )
            or []
        )

        power_state = getattr(s, "power_state", None) or pick(d, "OS-EXT-STS:power_state", "OS_EXT_STS_power_state")
        task_state = getattr(s, "task_state", None) or pick(d, "OS-EXT-STS:task_state", "OS_EXT_STS_task_state")

        # Handle locked: if False/None -> None, if True -> get the reason string
        locked_bool = getattr(s, "locked", None)
        if locked_bool is None:
            locked_bool = pick(d, "locked")

        locked_reason = None
        if locked_bool:
            locked_reason = (
                getattr(s, "locked_reason", None) or pick(d, "locked_reason") or "Locked"
            )  # Default if no reason provided

        state = State(
            status=pick(d, "status"),
            power_state=int(power_state) if power_state is not None else None,
            task_state=task_state,
            progress=pick(d, "progress"),
            host_status=pick(d, "host_status"),
            locked=locked_reason,
            volumes_attached=(list(volumes_attached) if isinstance(volumes_attached, list) else []),
        )

        return VM(
            identity=identity,
            flavor=flavor,
            networking=nets,
            timestamps=timestamps,
            access=access,
            state=state,
        )
