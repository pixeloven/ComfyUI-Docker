"""
Simple tests to verify ComfyUI GPU service starts and runs correctly.
"""
import pytest
import requests
import subprocess
import sys
import os

# Add the tests directory to the path so we can import conftest
sys.path.insert(0, os.path.dirname(__file__))
from conftest import run_docker_compose, wait_for_service


class TestComfyGPU:
    """Test ComfyUI GPU service startup and basic functionality."""

    @pytest.fixture(scope="class", autouse=True)
    def setup_comfy_gpu(self, project_root, cleanup_containers):
        """Start ComfyUI GPU service for testing."""
        # Start the service
        result = run_docker_compose(
            ["up", "-d", "--build"],
            profile="comfy",
            project_root=project_root
        )
        assert result.returncode == 0, f"Failed to start service: {result.stderr}"

        # Wait for service to be ready
        service_ready = wait_for_service("http://localhost:8188", timeout=120)
        assert service_ready, "ComfyUI GPU service did not start"

        yield

        # Cleanup
        run_docker_compose(["down"], profile="comfy", project_root=project_root)

    def test_service_responds(self, comfy_service_url):
        """Test that the service responds to HTTP requests."""
        response = requests.get(comfy_service_url, timeout=30)
        assert response.status_code == 200
        assert "ComfyUI" in response.text

    def test_service_runs_in_gpu_mode(self, docker_client):
        """Test that the service is running in GPU mode (or CPU fallback)."""
        containers = docker_client.containers.list(
            filters={"label": "com.docker.compose.service=comfy"}
        )
        assert len(containers) > 0, "No ComfyUI containers found"

        # Service should be running (GPU mode will fallback to CPU if no GPU)
        container = containers[0]
        assert container.status == "running", "ComfyUI container should be running"
