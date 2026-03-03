#!/usr/bin/env python3
"""
Test Local Docker Registry
Tests connection to local registry on port 5000 and lists all images
"""

import sys
import requests
from pprint import pprint

def test_registry_connection(registry_url="localhost:5000"):
    """Test connection to local Docker registry"""
    print("\n" + "="*60)
    print("[TEST] Testing Local Registry Connection")
    print("="*60)
    
    print(f"[INFO] Registry URL: {registry_url}")
    
    try:
        # Test registry version endpoint
        version_url = f"http://{registry_url}/v2/"
        response = requests.get(version_url, timeout=5)
        response.raise_for_status()
        
        print(f"[SUCCESS] ✓ Connected to local registry successfully")
        print(f"[INFO] Registry is responding on port 5000")
        print(f"[INFO] API Version: v2")
        
        return True
    except requests.exceptions.ConnectionError:
        print(f"[ERROR] ✗ Cannot connect to registry at {registry_url}")
        print(f"[INFO] Make sure the registry is running:")
        print(f"       docker run -d -p 5000:5000 --name registry registry:2")
        return False
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] ✗ Failed to connect to registry: {e}")
        return False

def test_registry_catalog(registry_url="localhost:5000"):
    """List all repositories in the registry"""
    print("\n" + "="*60)
    print("[TEST] Listing Registry Catalog")
    print("="*60)
    
    try:
        catalog_url = f"http://{registry_url}/v2/_catalog"
        response = requests.get(catalog_url, timeout=10)
        response.raise_for_status()
        catalog = response.json()
        
        repositories = catalog.get("repositories", [])
        
        if not repositories:
            print("[WARNING] Registry is empty - no repositories found")
            return []
        
        print(f"[SUCCESS] ✓ Found {len(repositories)} repositories")
        print("\n[DATA] Repositories:")
        print("-" * 60)
        
        for idx, repo in enumerate(repositories, 1):
            print(f"{idx}. {repo}")
        
        return repositories
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] ✗ Failed to get catalog: {e}")
        return []

def test_repository_tags(registry_url, repositories):
    """List tags for each repository"""
    print("\n" + "="*60)
    print("[TEST] Listing Repository Tags")
    print("="*60)
    
    if not repositories:
        print("[INFO] No repositories to check for tags")
        return
    
    all_images = []
    
    for repo in repositories:
        try:
            tags_url = f"http://{registry_url}/v2/{repo}/tags/list"
            response = requests.get(tags_url, timeout=10)
            response.raise_for_status()
            tags_data = response.json()
            
            tags = tags_data.get("tags", [])
            
            print(f"\n[INFO] Repository: {repo}")
            
            if not tags:
                print(f"  [WARNING] No tags found")
                continue
            
            print(f"  [SUCCESS] ✓ Found {len(tags)} tags:")
            
            for tag in tags:
                full_image = f"{registry_url}/{repo}:{tag}"
                all_images.append(full_image)
                print(f"    - {tag}")
                print(f"      Full path: {full_image}")
                
                # Try to get manifest for more details
                try:
                    manifest_url = f"http://{registry_url}/v2/{repo}/manifests/{tag}"
                    manifest_response = requests.get(manifest_url, timeout=5)
                    if manifest_response.status_code == 200:
                        # Get content length as approximate size
                        size = len(manifest_response.content)
                        print(f"      Manifest size: {size} bytes")
                except:
                    pass  # Skip if manifest fetch fails
                    
        except requests.exceptions.RequestException as e:
            print(f"  [ERROR] ✗ Failed to get tags for {repo}: {e}")
    
    print("\n" + "="*60)
    print("[SUMMARY] All Available Images in Registry")
    print("="*60)
    
    if all_images:
        for img in all_images:
            print(f"  • {img}")
        print(f"\n[SUCCESS] Total: {len(all_images)} images in registry")
    else:
        print("[WARNING] No images with tags found in registry")

def test_registry_health(registry_url="localhost:5000"):
    """Check registry health and configuration"""
    print("\n" + "="*60)
    print("[TEST] Registry Health Check")
    print("="*60)
    
    try:
        # Test basic connectivity
        version_url = f"http://{registry_url}/v2/"
        response = requests.get(version_url, timeout=5)
        
        print(f"[INFO] Status Code: {response.status_code}")
        print(f"[INFO] Response Headers:")
        
        important_headers = ['Docker-Distribution-Api-Version', 'Content-Type', 'Date']
        for header in important_headers:
            if header in response.headers:
                print(f"  - {header}: {response.headers[header]}")
        
        if response.status_code == 200:
            print(f"[SUCCESS] ✓ Registry is healthy and responding")
        else:
            print(f"[WARNING] Registry responded with status {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] ✗ Health check failed: {e}")

def main():
    print("\n" + "="*60)
    print("Local Docker Registry Test Suite")
    print("="*60)
    
    registry_url = "localhost:5000"
    
    try:
        # Test registry connection
        if not test_registry_connection(registry_url):
            print("\n[ERROR] Cannot proceed without registry connection")
            sys.exit(1)
        
        # Test registry health
        test_registry_health(registry_url)
        
        # List catalog
        repositories = test_registry_catalog(registry_url)
        
        # List tags for each repository
        test_repository_tags(registry_url, repositories)
        
        print("\n" + "="*60)
        print("[SUCCESS] ✓ All registry tests completed")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n[ERROR] ✗ Test suite failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
