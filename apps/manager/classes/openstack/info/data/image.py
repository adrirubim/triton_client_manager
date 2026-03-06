from dataclasses import dataclass
from typing import Optional


@dataclass
class Image:
    # --- Identity ---
    id: str
    name: str
    status: str
    base_image_id: Optional[str] = None  # base_image_ref

    # --- Info ---
    size: Optional[int] = None  # size
    disk_format: Optional[str] = None  # disk_format
    required_ram: Optional[int] = None  # min_ram
    required_storage: Optional[int] = None  # min_disk

    # --- Time ---
    created_at: Optional[str] = None  # created_at
    updated_at: Optional[str] = None  # updated_at

    @classmethod
    def from_api(cls, data: dict) -> dict[str, "Image"]:
        images: dict[str, Image] = {}

        for raw in data.get("images", []):
            needed = {
                # --- Identity ---
                "id": raw["id"],
                "name": raw["name"],
                "status": raw["status"],
                "base_image_id": raw.get("base_image_ref"),
                # --- Info ---
                "size": raw.get("size"),
                "disk_format": raw.get("disk_format"),
                "required_ram": raw.get("min_ram"),
                "required_storage": raw.get("min_disk"),
                # --- Time ---
                "created_at": raw.get("created_at"),
                "updated_at": raw.get("updated_at"),
            }

            images[needed["id"]] = cls(**needed)

        return images
