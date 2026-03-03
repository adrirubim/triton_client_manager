#!/usr/bin/env python3
"""
Test GitLab API Connection and Registry Access
Tests authentication and ability to list container registries and their tags
"""

import yaml
import os
import sys
import requests

def load_config():
    """Load configuration from parent directory, token from environment"""
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    with open(config_path, "r") as f:
        config = yaml.load(f, Loader=yaml.SafeLoader)

    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        print("[ERROR] GITLAB_TOKEN environment variable is not set")
        sys.exit(1)
    config["token"] = token
    config["token_name"] = os.environ.get("GITLAB_TOKEN_NAME", "docker-vm-pull-token")

    return config

def test_gitlab_connection(config):
    """Test basic GitLab API connection"""
    print("\n" + "="*60)
    print("[TEST] Testing GitLab API Connection")
    print("="*60)
    
    gitlab_url = config["gitlab_url"].rstrip("/")
    token = config["token"]
    
    print(f"[INFO] GitLab URL: {gitlab_url}")
    print(f"[INFO] Token: {token[:4]}...{token[-4:]}")
    
    # Setup session
    session = requests.Session()
    session.headers.update({"PRIVATE-TOKEN": token})
    
    try:
        # Test API connection
        api_url = f"{gitlab_url}/api/v4/user"
        response = session.get(api_url, timeout=10)
        response.raise_for_status()
        user_data = response.json()
        
        print(f"[SUCCESS] ✓ Connected to GitLab successfully")
        print(f"[INFO] Authenticated as: {user_data.get('username', 'Unknown')}")
        print(f"[INFO] User ID: {user_data.get('id', 'Unknown')}")
        
        return session
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] ✗ Failed to connect to GitLab: {e}")
        sys.exit(1)

def test_project_access(session, config):
    """Test access to the specific project"""
    print("\n" + "="*60)
    print("[TEST] Testing Project Access")
    print("="*60)
    
    gitlab_url = config["gitlab_url"].rstrip("/")
    project_id = config["project_id"]
    
    print(f"[INFO] Project ID: {project_id}")
    
    try:
        project_url = f"{gitlab_url}/api/v4/projects/{project_id}"
        response = session.get(project_url, timeout=10)
        response.raise_for_status()
        project_data = response.json()
        
        print(f"[SUCCESS] ✓ Project access confirmed")
        print(f"[INFO] Project Name: {project_data.get('name', 'Unknown')}")
        print(f"[INFO] Project Path: {project_data.get('path_with_namespace', 'Unknown')}")
        print(f"[INFO] Visibility: {project_data.get('visibility', 'Unknown')}")
        
        return True
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] ✗ Failed to access project: {e}")
        return False

def test_registry_repositories(session, config):
    """Test listing container registry repositories"""
    print("\n" + "="*60)
    print("[TEST] Testing Container Registry Repositories")
    print("="*60)
    
    gitlab_url = config["gitlab_url"].rstrip("/")
    project_id = config["project_id"]
    
    try:
        repos_url = f"{gitlab_url}/api/v4/projects/{project_id}/registry/repositories"
        response = session.get(repos_url, timeout=10)
        response.raise_for_status()
        repos = response.json()
        
        if not repos:
            print("[WARNING] No container registries found in this project")
            return []
        
        print(f"[SUCCESS] ✓ Found {len(repos)} container registries")
        print("\n[DATA] Registry Repositories:")
        print("-" * 60)
        
        for idx, repo in enumerate(repos, 1):
            print(f"\n{idx}. Repository ID: {repo['id']}")
            print(f"   Name: {repo.get('name', 'N/A')}")
            print(f"   Location: {repo.get('location', 'N/A')}")
            print(f"   Path: {repo.get('path', 'N/A')}")
            print(f"   Created: {repo.get('created_at', 'N/A')}")
        
        return repos
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] ✗ Failed to list registries: {e}")
        return []

def test_registry_tags(session, config, repos):
    """Test listing tags for each registry repository"""
    print("\n" + "="*60)
    print("[TEST] Testing Registry Tags")
    print("="*60)
    
    if not repos:
        print("[INFO] No repositories to check for tags")
        return
    
    gitlab_url = config["gitlab_url"].rstrip("/")
    project_id = config["project_id"]
    
    all_images = []
    
    for repo in repos:
        repo_id = repo['id']
        repo_location = repo.get('location', 'Unknown')
        
        try:
            tags_url = f"{gitlab_url}/api/v4/projects/{project_id}/registry/repositories/{repo_id}/tags"
            response = session.get(tags_url, timeout=10)
            response.raise_for_status()
            tags = response.json()
            
            print(f"\n[INFO] Repository: {repo_location}")
            
            if not tags:
                print(f"  [WARNING] No tags found")
                continue
            
            print(f"  [SUCCESS] ✓ Found {len(tags)} tags:")
            
            for tag in tags:
                tag_name = tag.get('name', 'unknown')
                full_image = f"{repo_location}:{tag_name}"
                all_images.append(full_image)
                
                print(f"    - {tag_name}")
                print(f"      Full path: {full_image}")
                print(f"      Created: {tag.get('created_at', 'N/A')}")
                print(f"      Size: {tag.get('total_size', 0) / (1024*1024):.2f} MB")
                
        except requests.exceptions.RequestException as e:
            print(f"  [ERROR] ✗ Failed to get tags: {e}")
    
    print("\n" + "="*60)
    print("[SUMMARY] All Available Images")
    print("="*60)
    
    if all_images:
        for img in all_images:
            print(f"  • {img}")
        print(f"\n[SUCCESS] Total: {len(all_images)} images available")
    else:
        print("[WARNING] No images with tags found")

def main():
    print("\n" + "="*60)
    print("GitLab Container Registry Test Suite")
    print("="*60)
    
    try:
        # Load configuration
        config = load_config()
        print("[INFO] Configuration loaded successfully")
        
        # Run tests
        session = test_gitlab_connection(config)
        test_project_access(session, config)
        repos = test_registry_repositories(session, config)
        test_registry_tags(session, config, repos)
        
        print("\n" + "="*60)
        print("[SUCCESS] ✓ All GitLab tests completed")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n[ERROR] ✗ Test suite failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
