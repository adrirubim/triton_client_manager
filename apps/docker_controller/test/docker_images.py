#!/usr/bin/env python3
"""
Test Local Docker Images
Tests connection to Docker daemon and lists all local images
"""

import sys
import docker
from datetime import datetime


def test_docker_connection():
    """Test connection to Docker daemon"""
    print("\n" + "="*60)
    print("[TEST] Testing Docker Daemon Connection")
    print("="*60)
    
    try:
        client = docker.from_env()
        
        # Get Docker version info
        version_info = client.version()
        
        print(f"[SUCCESS] ✓ Connected to Docker daemon successfully")
        print(f"[INFO] Docker Version: {version_info.get('Version', 'Unknown')}")
        print(f"[INFO] API Version: {version_info.get('ApiVersion', 'Unknown')}")
        print(f"[INFO] OS/Arch: {version_info.get('Os', 'Unknown')}/{version_info.get('Arch', 'Unknown')}")
        
        return client
    except docker.errors.DockerException as e:
        print(f"[ERROR] ✗ Failed to connect to Docker daemon: {e}")
        print("[INFO] Make sure Docker is running and you have permission to access it")
        sys.exit(1)

def format_size(size_bytes):
    """Format bytes to human readable size"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"

def format_timestamp(timestamp):
    """Format timestamp to readable date"""
    try:
        if isinstance(timestamp, str):
            # Parse ISO format timestamp
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return str(timestamp)

def test_list_images(client):
    """List all Docker images on the local system"""
    print("\n" + "="*60)
    print("[TEST] Listing Local Docker Images")
    print("="*60)
    
    try:
        images = client.images.list()
        
        if not images:
            print("[WARNING] No Docker images found on local system")
            return
        
        print(f"[SUCCESS] ✓ Found {len(images)} Docker images")
        print("\n[DATA] Local Docker Images:")
        print("-" * 60)
        
        for idx, image in enumerate(images, 1):
            print(f"\n{idx}. Image ID: {image.id[:19]}")
            
            # Get tags
            tags = image.tags
            if tags:
                print(f"   Tags:")
                for tag in tags:
                    print(f"     - {tag}")
            else:
                print(f"   Tags: <none>")
            
            # Get attributes
            attrs = image.attrs
            print(f"   Size: {format_size(attrs.get('Size', 0))}")
            print(f"   Created: {format_timestamp(attrs.get('Created', 'Unknown'))}")
            
            # Get repo digests if available
            repo_digests = attrs.get('RepoDigests', [])
            if repo_digests:
                print(f"   Repo Digests:")
                for digest in repo_digests[:2]:  # Show first 2
                    print(f"     - {digest}")
        
        print("\n" + "-" * 60)
        print(f"[SUMMARY] Total images: {len(images)}")
        
        # Calculate total size
        total_size = sum(img.attrs.get('Size', 0) for img in images)
        print(f"[SUMMARY] Total size: {format_size(total_size)}")
        
    except docker.errors.APIError as e:
        print(f"[ERROR] ✗ Failed to list images: {e}")

def test_filter_gitlab_images(client, gitlab_registry="registry.example.com"):
    """Filter and show only GitLab registry images"""
    print("\n" + "="*60)
    print(f"[TEST] Filtering GitLab Registry Images ({gitlab_registry})")
    print("="*60)
    
    try:
        images = client.images.list()
        gitlab_images = []
        
        for image in images:
            for tag in image.tags:
                if gitlab_registry in tag:
                    gitlab_images.append((image, tag))
        
        if not gitlab_images:
            print(f"[INFO] No images from {gitlab_registry} found locally")
            return
        
        print(f"[SUCCESS] ✓ Found {len(gitlab_images)} images from GitLab registry")
        print("\n[DATA] GitLab Images:")
        print("-" * 60)
        
        for idx, (image, tag) in enumerate(gitlab_images, 1):
            attrs = image.attrs
            print(f"\n{idx}. {tag}")
            print(f"   Image ID: {image.id[:19]}")
            print(f"   Size: {format_size(attrs.get('Size', 0))}")
            print(f"   Created: {format_timestamp(attrs.get('Created', 'Unknown'))}")
        
    except docker.errors.APIError as e:
        print(f"[ERROR] ✗ Failed to filter images: {e}")

def test_filter_local_registry_images(client, local_registry="localhost:5000"):
    """Filter and show only local registry images"""
    print("\n" + "="*60)
    print(f"[TEST] Filtering Local Registry Images ({local_registry})")
    print("="*60)
    
    try:
        images = client.images.list()
        local_images = []
        
        for image in images:
            for tag in image.tags:
                if local_registry in tag:
                    local_images.append((image, tag))
        
        if not local_images:
            print(f"[INFO] No images tagged for {local_registry} found locally")
            return
        
        print(f"[SUCCESS] ✓ Found {len(local_images)} images tagged for local registry")
        print("\n[DATA] Local Registry Tagged Images:")
        print("-" * 60)
        
        for idx, (image, tag) in enumerate(local_images, 1):
            attrs = image.attrs
            print(f"\n{idx}. {tag}")
            print(f"   Image ID: {image.id[:19]}")
            print(f"   Size: {format_size(attrs.get('Size', 0))}")
            print(f"   Created: {format_timestamp(attrs.get('Created', 'Unknown'))}")
        
    except docker.errors.APIError as e:
        print(f"[ERROR] ✗ Failed to filter images: {e}")

def main():
    print("\n" + "="*60)
    print("Docker Local Images Test Suite")
    print("="*60)
    
    try:
        # Test Docker connection
        client = test_docker_connection()
        
        # List all images
        test_list_images(client)
        
        # Filter GitLab images
        test_filter_gitlab_images(client)
        
        # Filter local registry images
        test_filter_local_registry_images(client)
        
        print("\n" + "="*60)
        print("[SUCCESS] ✓ All Docker tests completed")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n[ERROR] ✗ Test suite failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
