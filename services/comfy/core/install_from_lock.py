#!/usr/bin/env python3
import os
import sys
import yaml
import subprocess
from pathlib import Path
import urllib.request
import ssl

# Allow unverified certificates for now to avoid build issues in some environments
ssl._create_default_https_context = ssl._create_unverified_context

LOCK_FILE = "comfy-lock.yaml"
APP_DIR = Path("/app")

def run_command(cmd, cwd=None):
    print(f"Running: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=cwd)

def install_nodes(nodes):
    if not nodes:
        return
    
    custom_nodes_dir = APP_DIR / "custom_nodes"
    custom_nodes_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Installing {len(nodes)} custom nodes...")
    
    for url, data in nodes.items():
        if data.get("disabled", False):
            print(f"Skipping disabled node: {url}")
            continue

        # Extract name from URL (simple heuristic)
        repo_name = url.split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
            
        repo_path = custom_nodes_dir / repo_name
        commit_hash = data.get("hash")
        
        if not repo_path.exists():
            print(f"Cloning {url} to {repo_path}...")
            run_command(["git", "clone", url, str(repo_path)])
        else:
            print(f"Repo exists at {repo_path}, fetching...")
            run_command(["git", "fetch", "origin"], cwd=repo_path)
            
        if commit_hash:
            print(f"Checking out {commit_hash} for {repo_name}...")
            run_command(["git", "checkout", commit_hash], cwd=repo_path)
        else:
            print(f"WARNING: No hash specified for {repo_name}, using HEAD.")

def download_file(url, path):
    print(f"Downloading {url} to {path}...")
    try:
        # Check if file exists and has size
        if path.exists() and path.stat().st_size > 0:
            print(f"File {path} already exists, skipping download (size check only).")
            return

        urllib.request.urlretrieve(url, path)
        print(f"Successfully downloaded {path.name}")
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        # Don't fail build for model download failure? Or strictly fail?
        # For now, strict fail is safer for "Lock" promise.
        sys.exit(1)

def install_models(models):
    if not models:
        return

    print(f"Installing {len(models)} models...")
    for model in models:
        url = model.get("url")
        paths = model.get("paths", [])
        
        if not url:
            print(f"Skipping model without URL: {model.get('model')}")
            continue
            
        for p in paths:
            rel_path = p.get("path")
            target_path = APP_DIR / rel_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            download_file(url, target_path)

def main():
    if len(sys.argv) > 1:
        lock_file_path = Path(sys.argv[1])
    else:
        lock_file_path = Path(LOCK_FILE)

    if not lock_file_path.exists():
        print(f"Lock file not found: {lock_file_path}")
        sys.exit(1)

    print(f"Loading lock file: {lock_file_path}")
    with open(lock_file_path, "r") as f:
        data = yaml.safe_load(f)

    # 1. Update Core ComfyUI if needed
    # (Assuming we are already in the repo or /app is the repo)
    core_hash = data.get("custom_nodes", {}).get("comfyui")
    if core_hash and (APP_DIR / ".git").exists():
        print(f"Ensuring ComfyUI Core is at {core_hash}...")
        run_command(["git", "checkout", core_hash], cwd=APP_DIR)

    # 2. Install Custom Nodes
    git_nodes = data.get("custom_nodes", {}).get("git_custom_nodes", {})
    install_nodes(git_nodes)

    # 3. Install Models
    models = data.get("models", [])
    install_models(models)

    print("Comfy-Lock installation complete.")

if __name__ == "__main__":
    main()
