"""
Pytest configuration and fixtures for ComfyUI Docker tests.
"""
import pytest
import docker
import time
import requests
import subprocess
import os
from pathlib import Path


@pytest.fixture(scope="session")
def docker_client():
    """Docker client fixture."""
    return docker.from_env()


@pytest.fixture(scope="session")
def project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def test_data_dir(project_root):
    """Create and return test data directory."""
    test_data = project_root / "tests" / "data"
    test_data.mkdir(exist_ok=True)
    return test_data


@pytest.fixture(scope="session")
def test_output_dir(project_root):
    """Create and return test output directory."""
    test_output = project_root / "tests" / "output"
    test_output.mkdir(exist_ok=True)
    return test_output


def wait_for_service(url, timeout=120, interval=5):
    """Wait for a service to become available."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(interval)
    return False


@pytest.fixture
def comfy_service_url():
    """ComfyUI service URL for testing."""
    return "http://localhost:8188"


@pytest.fixture
def comfy_cpu_service_url():
    """ComfyUI CPU service URL for testing."""
    return "http://localhost:8189"


def run_docker_compose(command, profile=None, project_root=None):
    """Helper function to run docker-compose commands."""
    if project_root is None:
        project_root = Path(__file__).parent.parent
    
    cmd = ["docker", "compose"]
    if profile:
        cmd.extend(["--profile", profile])
    cmd.extend(command)
    
    result = subprocess.run(
        cmd,
        cwd=project_root,
        capture_output=True,
        text=True
    )
    return result


@pytest.fixture(scope="session")
def cleanup_containers():
    """Cleanup fixture to ensure containers are stopped after tests."""
    yield
    # Cleanup after all tests
    project_root = Path(__file__).parent.parent
    run_docker_compose(["down", "--remove-orphans"], project_root=project_root)
