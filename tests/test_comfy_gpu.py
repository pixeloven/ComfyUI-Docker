"""
Essential tests for ComfyUI GPU mode functionality.
Focused on critical functionality for single developer maintenance.
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
    """Essential tests for ComfyUI GPU mode."""

    @pytest.fixture(scope="class", autouse=True)
    def setup_comfy_gpu(self, project_root, cleanup_containers):
        """Setup ComfyUI GPU service for testing."""
        # Build and start the service
        build_result = run_docker_compose(
            ["up", "-d", "--build"],
            profile="comfy",
            project_root=project_root
        )
        assert build_result.returncode == 0, f"Build/start failed: {build_result.stderr}"

        # Wait for service to be ready
        service_ready = wait_for_service("http://localhost:8188", timeout=120)
        assert service_ready, "ComfyUI GPU service did not start within timeout"

        yield

        # Cleanup
        run_docker_compose(["down"], profile="comfy", project_root=project_root)

    def test_gpu_service_responds(self, comfy_service_url):
        """Test that ComfyUI GPU service is responding."""
        response = requests.get(comfy_service_url, timeout=30)
        assert response.status_code == 200
        assert "ComfyUI" in response.text

    def test_gpu_essential_endpoints(self, comfy_service_url):
        """Test essential API endpoints."""
        endpoints = ["/system_stats", "/queue"]
        for endpoint in endpoints:
            response = requests.get(f"{comfy_service_url}{endpoint}", timeout=30)
            assert response.status_code == 200, f"Endpoint {endpoint} failed"

    def test_gpu_mode_configuration(self, docker_client):
        """Test that GPU mode is configured correctly."""
        containers = docker_client.containers.list(
            filters={"label": "com.docker.compose.service=comfy"}
        )
        assert len(containers) > 0, "No ComfyUI GPU containers found"

        container = containers[0]
        env_vars = {
            item.split('=')[0]: item.split('=', 1)[1]
            for item in container.attrs['Config']['Env']
            if '=' in item
        }

        # Should not have --cpu flag in GPU mode
        cli_args = env_vars.get('CLI_ARGS', '')
        assert '--cpu' not in cli_args, "GPU mode should not have --cpu flag"

    @pytest.mark.skipif(
        subprocess.run(["nvidia-smi"], capture_output=True).returncode != 0,
        reason="No NVIDIA GPU available"
    )
    def test_gpu_device_access(self, docker_client):
        """Test that GPU container has GPU device access (if GPU available)."""
        containers = docker_client.containers.list(
            filters={"label": "com.docker.compose.service=comfy"}
        )
        assert len(containers) > 0, "No ComfyUI GPU containers found"

        container = containers[0]
        host_config = container.attrs['HostConfig']

        # Check for GPU device allocation
        device_requests = host_config.get('DeviceRequests', [])
        assert len(device_requests) > 0, "GPU container should have device requests"
