import yaml
import os
import time
import requests
import docker
import logging
import base64
from urllib.parse import urlparse

from guardrails import is_allowed_image, validate_supply_chain_guardrails
from gitlab_pagination import next_page_from_headers
from tag_selection import choose_tag_name

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


def _normalize_local_registry(config: dict) -> tuple[str, str]:
    """
    Returns (local_registry_hostport, local_registry_scheme).

    - Tagging images requires host:port (no scheme).
    - HTTP calls to the registry require scheme + host:port.
    """
    cfg_value = (config.get("local_registry") or "localhost:5000").strip()
    cfg_scheme = (config.get("local_registry_scheme") or "").strip()
    env_scheme = (os.environ.get("LOCAL_REGISTRY_SCHEME") or "").strip()
    scheme = (env_scheme or cfg_scheme or "http").lower()

    # Allow config to provide a full URL like "http://localhost:5000".
    if "://" in cfg_value:
        parsed = urlparse(cfg_value)
        if parsed.scheme:
            scheme = parsed.scheme.lower()
        hostport = parsed.netloc or parsed.path  # path fallback for odd inputs
        return hostport.strip("/"), scheme

    return cfg_value, scheme


def _local_registry_base_url(local_registry_hostport: str, scheme: str) -> str:
    scheme_norm = (scheme or "http").lower()
    if scheme_norm not in {"http", "https"}:
        raise ValueError(
            f"Invalid local_registry_scheme: {scheme!r} (expected 'http' or 'https')"
        )
    hostport = (local_registry_hostport or "localhost:5000").strip().rstrip("/")
    return f"{scheme_norm}://{hostport}"


def config_dict():
    config_path = os.path.join(os.getcwd(), "config.yaml")
    with open(config_path, "r") as f:
        config = yaml.load(f, Loader=yaml.SafeLoader)

    token = os.environ.get("REGISTRY_TOKEN")
    if not token:
        raise ValueError("REGISTRY_TOKEN environment variable is not set")
    config["token"] = token
    config["token_name"] = os.environ.get("REGISTRY_TOKEN_NAME", "docker-vm-pull-token")
    config["registry_username"] = os.environ.get(
        "REGISTRY_USERNAME", config.get("registry_username") or ""
    )

    return config


def session_setup(config: dict):
    provider = (config.get("provider") or "gitlab").strip().lower()
    session = requests.Session()
    if provider == "gitlab":
        session.headers.update({"PRIVATE-TOKEN": config["token"]})
    return session


def _gitlab_get_all_pages(
    *,
    session: requests.Session,
    url: str,
    timeout_s: int = 30,
    per_page: int = 100,
) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        resp = session.get(
            url,
            params={"per_page": per_page, "page": page},
            timeout=timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            items.extend([x for x in data if isinstance(x, dict)])
        else:
            # GitLab endpoints we use should be list-based; fail safe if changed.
            raise ValueError(f"Unexpected GitLab response type for {url!r}: {type(data)}")

        next_page = next_page_from_headers(resp.headers)
        if not next_page:
            return items
        page = next_page


def docker_setup(config: dict):
    client = docker.from_env()

    provider = (config.get("provider") or "gitlab").strip().lower()
    if provider == "ghcr":
        username = (config.get("registry_username") or "").strip()
        if not username:
            raise ValueError(
                "REGISTRY_USERNAME (or config.registry_username) is required for provider=ghcr"
            )
        registry = "ghcr.io"
        logger.info(f"Logging into GHCR: {registry}")
        try:
            client.login(
                username=username,
                password=config["token"],
                registry=registry,
            )
            logger.info("✓ Logged into GHCR successfully")
        except Exception as e:
            logger.error(f"Failed to login to GHCR: {e}")
            raise
    else:
        gitlab_url = config["gitlab_url"].rstrip("/")
        registry = gitlab_url.replace("https://", "").replace("http://", "") + ":5050"
        logger.info(f"Logging into GitLab registry: {registry}")
        try:
            client.login(
                username="oauth2",
                password=config["token"],
                registry=registry,
            )
            logger.info("✓ Logged into GitLab registry successfully")
        except Exception as e:
            logger.error(f"Failed to login to GitLab registry: {e}")
            raise

    return client


def return_images_dict(session: requests.Session, config: dict) -> list[tuple]:
    """Get list of repository IDs and locations from GitLab"""
    provider = (config.get("provider") or "gitlab").strip().lower()
    if provider != "gitlab":
        raise ValueError("return_images_dict is only valid for provider=gitlab")

    # --- Repo Url ---
    gitlab_url = config["gitlab_url"].rstrip("/")
    project_id = int(config["project_id"])
    repos_url = f"{gitlab_url}/api/v4/projects/{project_id}/registry/repositories"

    per_page = int(config.get("gitlab_per_page") or 100)
    repos = _gitlab_get_all_pages(
        session=session, url=repos_url, timeout_s=30, per_page=per_page
    )

    return [(image["id"], image["location"]) for image in repos]


def return_images_path(
    session: requests.Session, config: dict, image_dict: list[tuple]
) -> list[str]:
    """Get full image paths with tags from GitLab"""
    provider = (config.get("provider") or "gitlab").strip().lower()
    if provider != "gitlab":
        raise ValueError("return_images_path is only valid for provider=gitlab")

    # --- image Url ---
    gitlab_url = config["gitlab_url"].rstrip("/")
    project_id = int(config["project_id"])
    per_page = int(config.get("gitlab_per_page") or 100)
    tag_strategy = (config.get("tag_selection_strategy") or "updated_at").strip().lower()
    tag_name_regex = (config.get("tag_name_regex") or "").strip() or None

    images_path = []
    for id, location in image_dict:
        tags_url = (
            f"{gitlab_url}/api/v4/projects/{project_id}/registry/repositories/{id}/tags"
        )

        tags = _gitlab_get_all_pages(
            session=session, url=tags_url, timeout_s=30, per_page=per_page
        )
        tag_name = choose_tag_name(
            tags=tags, strategy=tag_strategy, name_regex=tag_name_regex
        )
        if tag_name:
            images_path.append(f"{location}:{tag_name}")

    return images_path


def _ghcr_basic_auth_header(username: str, token: str) -> str:
    raw = f"{username}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _ghcr_list_tags(
    *, session: requests.Session, owner: str, image: str, username: str, token: str
) -> list[str]:
    # Registry v2 tags list endpoint.
    # https://ghcr.io/v2/<owner>/<image>/tags/list
    url = f"https://ghcr.io/v2/{owner}/{image}/tags/list"
    headers = {"Authorization": _ghcr_basic_auth_header(username, token)}
    resp = session.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    tags = data.get("tags") or []
    return [str(t).strip() for t in tags if str(t).strip()]


def ghcr_images_path(session: requests.Session, config: dict) -> list[str]:
    owner = (config.get("ghcr_owner") or "").strip()
    username = (config.get("registry_username") or "").strip()
    token = config["token"]
    remote_images = config.get("remote_images") or []
    if isinstance(remote_images, str):
        remote_images = [remote_images]
    remote_default_tag = (config.get("remote_default_tag") or "latest").strip()

    images_path: list[str] = []
    for item in remote_images:
        raw = str(item).strip()
        if not raw:
            continue
        if ":" in raw:
            image, tag = raw.rsplit(":", 1)
        else:
            image, tag = raw, remote_default_tag

        # Optional: if tag is "auto", pick latest lexicographically (stable, but not time-based).
        if tag == "auto":
            tags = _ghcr_list_tags(
                session=session, owner=owner, image=image, username=username, token=token
            )
            if not tags:
                continue
            tag = sorted(tags)[-1]

        images_path.append(f"ghcr.io/{owner}/{image}:{tag}")

    return images_path


def convert_to_local_tag(
    gitlab_image_path: str, local_registry: str = "localhost:5000"
) -> str:
    """Convert GitLab image path to local registry format with short names"""
    # Extract only the image name (last part) and tag from GitLab path
    # Example: git2004.vsrv.one:5050/lavoti/triton_client_manager/image:tag
    # Should become: localhost:5000/image:tag

    if ":" in gitlab_image_path:
        # Split by first occurrence of ':' to separate registry from rest
        parts = gitlab_image_path.split("/", 1)
        if len(parts) > 1:
            # Get the full path with tag: lavoti/triton_client_manager/image:tag
            image_path_with_tag = parts[1]
            # Extract only the last part (image name with tag): image:tag
            image_name_with_tag = image_path_with_tag.split("/")[-1]
            return f"{local_registry}/{image_name_with_tag}"

    return f"{local_registry}/{gitlab_image_path}"


def get_local_registry_images(
    *, local_registry_hostport: str, local_registry_scheme: str
) -> set[str]:
    """Query the local registry to get list of existing images"""
    base_url = _local_registry_base_url(local_registry_hostport, local_registry_scheme)
    try:
        catalog_url = f"{base_url}/v2/_catalog"
        response = requests.get(catalog_url, timeout=10)
        response.raise_for_status()
        catalog = response.json()

        existing_images = set()
        repositories = catalog.get("repositories", [])

        # For each repository, get its tags
        for repo in repositories:
            tags_url = f"{base_url}/v2/{repo}/tags/list"
            tags_response = requests.get(tags_url, timeout=10)
            tags_response.raise_for_status()
            tags_data = tags_response.json()

            tags = tags_data.get("tags", [])
            for tag in tags:
                existing_images.add(f"{local_registry_hostport}/{repo}:{tag}")

        return existing_images
    except Exception as e:
        logger.warning(f"Could not query local registry: {e}")
        return set()


def image_exists_in_local_registry(local_tag: str, existing_images: set[str]) -> bool:
    """Check if an image already exists in the local registry"""
    return local_tag in existing_images


def detect_platform(image_path: str) -> str:
    """Detect platform from image name/tag"""
    image_lower = image_path.lower()

    # Check for ARM indicators
    if "arm" in image_lower or "aarch64" in image_lower or "ampereone" in image_lower:
        return "linux/arm64"
    # Check for AMD64 indicators
    elif "amd64" in image_lower or "x86_64" in image_lower or "x86-64" in image_lower:
        return "linux/amd64"
    else:
        # No platform detected, return None to use default
        return None


def pull_image_with_platform(client, image_path: str):
    """Pull image with platform detection for multi-architecture support"""
    platform = detect_platform(image_path)

    if platform:
        logger.info(f"Detected platform: {platform}")
        try:
            return client.images.pull(image_path, platform=platform)
        except docker.errors.APIError as e:
            # If platform-specific pull failed, try without platform
            logger.warning(f"Platform-specific pull failed, trying default: {e}")
            return client.images.pull(image_path)
    else:
        logger.info("Using default platform")
        return client.images.pull(image_path)


def main():
    config = config_dict()
    client = docker_setup(config)
    session = session_setup(config)

    local_registry, local_registry_scheme = _normalize_local_registry(config)
    allowed_images, allowed_regex = validate_supply_chain_guardrails(
        config=config,
        local_registry_hostport=local_registry,
        local_registry_scheme=local_registry_scheme,
    )
    provider = (config.get("provider") or "gitlab").strip().lower()

    logger.info("Starting image sync service...")
    logger.info(f"Provider: {provider}")
    if provider == "gitlab":
        logger.info(f"GitLab: {config['gitlab_url']}")
    else:
        logger.info(f"GHCR owner: {config.get('ghcr_owner')}")
    logger.info(f"Local Registry: {local_registry_scheme}://{local_registry}")
    logger.info(
        f"Allowlist enabled: {len(allowed_images)} explicit image names, "
        f"{len(allowed_regex)} regex patterns"
    )
    logger.info("-" * 50)

    while True:
        try:
            # --- Query local registry to see what already exists ---
            logger.info("Querying local registry for existing images...")
            existing_images = get_local_registry_images(
                local_registry_hostport=local_registry,
                local_registry_scheme=local_registry_scheme,
            )
            if existing_images:
                logger.info(f"Found {len(existing_images)} images in local registry")
            else:
                logger.info("Local registry is empty or unreachable")

            if provider == "gitlab":
                images_dict = return_images_dict(session, config)
                if not images_dict:
                    logger.warning("No repositories found in GitLab")
                    continue

                images_dict = [
                    (repo_id, location)
                    for (repo_id, location) in images_dict
                    if is_allowed_image(
                        location=location,
                        allowed_images=allowed_images,
                        allowed_regex=allowed_regex,
                    )
                ]
                if not images_dict:
                    logger.warning(
                        "No repositories matched allowlist; nothing to sync this cycle."
                    )
                    time.sleep(60)
                    continue

                images_path = return_images_path(session, config, images_dict)
            else:
                # For GHCR we do not enumerate repositories via API; we use explicit remote_images list.
                images_path = ghcr_images_path(session, config)

            if not images_path:
                logger.warning("No tagged images found")
                continue

            # --- Process each image ---
            for image_path in images_path:
                # Convert to local tag format
                local_tag = convert_to_local_tag(image_path, local_registry)

                # Skip if already present in local registry
                if image_exists_in_local_registry(local_tag, existing_images):
                    logger.debug(f"SKIP: {local_tag} already exists in local registry")
                    continue

                try:
                    # Pull from GitLab with platform awareness
                    logger.info(f"Pulling {image_path}...")
                    image = pull_image_with_platform(client, image_path)
                    logger.info(f"✓ Successfully pulled {image_path}")

                    # Tag for local registry
                    logger.info(f"Tagging as {local_tag}...")
                    image.tag(local_tag)
                    logger.info("✓ Successfully tagged")

                    # Push to local registry
                    logger.info(f"Pushing to {local_tag}...")
                    client.images.push(local_tag)
                    logger.info("✓ Successfully pushed to local registry")

                    logger.info(f"SUCCESS: Completed processing {image_path}")
                    logger.info("-" * 50)

                except docker.errors.APIError as e:
                    logger.error(f"Docker API error for {image_path}: {e}")
                except Exception as e:
                    logger.error(f"Failed to process {image_path}: {e}")

            time.sleep(60)
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error connecting to GitLab: {e}")
            time.sleep(60)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
