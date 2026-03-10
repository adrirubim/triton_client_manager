import yaml
import os
import time
import requests
import docker
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

def config_dict():
    config_path = os.path.join(os.getcwd(), "config.yaml")
    config = yaml.load(open(config_path, "r"), Loader=yaml.SafeLoader)

    token = os.environ.get("REGISTRY_TOKEN")
    if not token:
        raise ValueError("REGISTRY_TOKEN environment variable is not set")
    config["token"] = token
    config["token_name"] = os.environ.get("REGISTRY_TOKEN_NAME", "docker-vm-pull-token")

    return config

def session_setup(config: dict):
    session = requests.Session()
    session.headers.update({"PRIVATE-TOKEN": config["token"]})
    return session

def docker_setup(config: dict):
    client = docker.from_env()
    
    # Extract registry domain from GitLab URL and add port
    gitlab_url = config["gitlab_url"].rstrip("/")
    registry = gitlab_url.replace("https://", "").replace("http://", "") + ":5050"
    
    logger.info(f"Logging into GitLab registry: {registry}")
    
    try:
        client.login(
            username="oauth2",  # GitLab accepts "oauth2" as username with personal access token
            password=config["token"],
            registry=registry
        )
        logger.info("✓ Logged into GitLab registry successfully")
    except Exception as e:
        logger.error(f"Failed to login to GitLab registry: {e}")
        raise
    
    return client

def return_images_dict(session: requests.Session, config: dict) -> list[tuple]:
    """Get list of repository IDs and locations from GitLab"""
    # --- Repo Url ---
    gitlab_url = config["gitlab_url"].rstrip("/")
    project_id = int(config["project_id"])
    repos_url = f"{gitlab_url}/api/v4/projects/{project_id}/registry/repositories"

    # --- Request ---
    repos = session.get(repos_url, timeout=30)
    repos.raise_for_status()
    repos = repos.json()

    return [(image["id"], image["location"]) for image in repos]

def return_images_path(session: requests.Session, config: dict, image_dict: list[tuple]) -> list[str]:
    """Get full image paths with tags from GitLab"""
    # --- image Url ---
    gitlab_url = config["gitlab_url"].rstrip("/")
    project_id = int(config["project_id"])

    images_path = []
    for (id, location) in image_dict:
        tags_url = f"{gitlab_url}/api/v4/projects/{project_id}/registry/repositories/{id}/tags"
        
        # --- Request ---
        tags = session.get(tags_url, timeout=30)
        tags.raise_for_status()
        tags = tags.json()

        # --- If tag found --- (should always find it)
        if tags:
            # Get the first tag (most recent)
            tag_name = tags[0]["name"]
            images_path.append(f"{location}:{tag_name}")

    return images_path

def convert_to_local_tag(gitlab_image_path: str, local_registry: str = "localhost:5000") -> str:
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
            image_name_with_tag = image_path_with_tag.split('/')[-1]
            return f"{local_registry}/{image_name_with_tag}"
    
    return f"{local_registry}/{gitlab_image_path}"

def get_local_registry_images(local_registry: str = "localhost:5000") -> set[str]:
    """Query the local registry to get list of existing images"""
    try:
        catalog_url = f"http://{local_registry}/v2/_catalog"
        response = requests.get(catalog_url, timeout=10)
        response.raise_for_status()
        catalog = response.json()
        
        existing_images = set()
        repositories = catalog.get("repositories", [])
        
        # For each repository, get its tags
        for repo in repositories:
            tags_url = f"http://{local_registry}/v2/{repo}/tags/list"
            tags_response = requests.get(tags_url, timeout=10)
            tags_response.raise_for_status()
            tags_data = tags_response.json()
            
            tags = tags_data.get("tags", [])
            for tag in tags:
                existing_images.add(f"{local_registry}/{repo}:{tag}")
        
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

    local_registry = config.get("local_registry", "localhost:5000")

    logger.info("Starting image sync service...")
    logger.info(f"GitLab: {config['gitlab_url']}")
    logger.info(f"Local Registry: {local_registry}")
    logger.info("-" * 50)

    while True:
        try:
            time.sleep(60)

            # --- Query local registry to see what already exists ---
            logger.info("Querying local registry for existing images...")
            existing_images = get_local_registry_images(local_registry)
            if existing_images:
                logger.info(f"Found {len(existing_images)} images in local registry")
            else:
                logger.info("Local registry is empty or unreachable")

            # --- Get repository information from GitLab ---
            images_dict = return_images_dict(session, config)
            if not images_dict:
                logger.warning("No repositories found in GitLab")
                continue

            # --- Get full image paths with tags ---
            images_path = return_images_path(session, config, images_dict)
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

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error connecting to GitLab: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()
