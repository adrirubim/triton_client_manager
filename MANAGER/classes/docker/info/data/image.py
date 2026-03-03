import logging
from dataclasses import dataclass
from typing import Optional
import requests

logger = logging.getLogger(__name__)


@dataclass
class Image:
    """Docker image from catalog registry"""
    # --- Identity ---
    name: str              # e.g., "tritonserver"
    tag: str               # e.g., "24.01-py3"
    digest: str            # SHA256 digest
    
    # --- Info ---
    size: Optional[int] = None           # Size in bytes
    architecture: Optional[str] = None   # amd64, arm64, etc.
    os: Optional[str] = None             # linux, windows
    
    # --- Time ---
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    @classmethod
    def from_api(cls, data: dict) -> dict[str, "Image"]:
        """
        Parse Docker Registry V2 API response
        Expected format from /v2/<name>/tags/list and /v2/<name>/manifests/<tag>
        
        Args:
            data: Dictionary containing:
                - name: Repository name (e.g., "tritonserver")
                - tags: List of tags (e.g., ["24.01-py3", "24.02-py3"])
                - endpoint: Registry endpoint for fetching manifests
        
        Returns: 
            dict[f"{name}:{tag}", Image]: Dictionary keyed by "name:tag"
        """
        images: dict[str, Image] = {}
        
        repo_name = data.get("name", "")
        tags = data.get("tags", [])
        endpoint = data.get("endpoint", "")
        
        if not repo_name or not tags:
            return images
        
        for tag in tags:
            try:
                # Fetch manifest for this specific tag to get digest and details
                manifest_url = f"{endpoint}/v2/{repo_name}/manifests/{tag}"
                headers = {
                    "Accept": "application/vnd.docker.distribution.manifest.v2+json"
                }
                
                response = requests.get(manifest_url, headers=headers, timeout=5)
                response.raise_for_status()
                
                # Get digest from response headers
                digest = response.headers.get("Docker-Content-Digest", "")
                
                # Parse manifest data
                manifest = response.json()
                
                # Extract config details if available
                config_digest = manifest.get("config", {}).get("digest", "")
                size = manifest.get("config", {}).get("size", 0)
                
                # Try to get more details from config blob (optional, may require additional request)
                architecture = None
                os_type = None
                created_at = None
                
                # Create image key
                image_key = f"{repo_name}:{tag}"
                
                # Create Image instance
                images[image_key] = cls(
                    name=repo_name,
                    tag=tag,
                    digest=digest or config_digest,
                    size=size,
                    architecture=architecture,
                    os=os_type,
                    created_at=created_at,
                    updated_at=None
                )
                
            except Exception as e:
                logger.warning("Failed to fetch manifest for %s:%s: %s", repo_name, tag, e)
                # Create minimal image entry even if manifest fetch fails
                image_key = f"{repo_name}:{tag}"
                images[image_key] = cls(
                    name=repo_name,
                    tag=tag,
                    digest="",
                    size=None,
                    architecture=None,
                    os=None,
                    created_at=None,
                    updated_at=None
                )
        
        return images
