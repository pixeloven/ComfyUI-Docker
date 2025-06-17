"""
Essential tests for ComfyUI CPU-only mode functionality.
Focused on critical functionality for single developer maintenance.
"""
import pytest
import requests
import sys
import os

# Add the tests directory to the path so we can import conftest
sys.path.insert(0, os.path.dirname(__file__))
from conftest import run_docker_compose, wait_for_service


class TestComfyCPU:
    """Essential tests for ComfyUI CPU mode."""

    @pytest.fixture(scope="class", autouse=True)
    def setup_comfy_cpu(self, project_root, cleanup_containers):
        """Setup ComfyUI CPU service for testing."""
        # Build and start the service
        build_result = run_docker_compose(
            ["up", "-d", "--build"],
            profile="comfy-cpu",
            project_root=project_root
        )
        assert build_result.returncode == 0, f"Build/start failed: {build_result.stderr}"

        # Wait for service to be ready
        service_ready = wait_for_service("http://localhost:8189", timeout=120)
        assert service_ready, "ComfyUI CPU service did not start within timeout"

        yield

        # Cleanup
        run_docker_compose(["down"], profile="comfy-cpu", project_root=project_root)

    def test_cpu_service_responds(self, comfy_cpu_service_url):
        """Test that ComfyUI CPU service is responding."""
        response = requests.get(comfy_cpu_service_url, timeout=30)
        assert response.status_code == 200
        assert "ComfyUI" in response.text

    def test_cpu_essential_endpoints(self, comfy_cpu_service_url):
        """Test essential API endpoints."""
        endpoints = ["/system_stats", "/queue"]
        for endpoint in endpoints:
            response = requests.get(f"{comfy_cpu_service_url}{endpoint}", timeout=30)
            assert response.status_code == 200, f"Endpoint {endpoint} failed"

    def test_cpu_mode_configuration(self, docker_client):
        """Test that CPU mode is configured correctly."""
        containers = docker_client.containers.list(
            filters={"label": "com.docker.compose.service=comfy-cpu"}
        )
        assert len(containers) > 0, "No ComfyUI CPU containers found"

        container = containers[0]
        env_vars = {
            item.split('=')[0]: item.split('=', 1)[1]
            for item in container.attrs['Config']['Env']
            if '=' in item
        }

        # Should have --cpu flag in CPU mode
        cli_args = env_vars.get('CLI_ARGS', '')
        assert '--cpu' in cli_args, "CPU mode should have --cpu flag"

    def test_cpu_no_gpu_devices(self, docker_client):
        """Test that CPU container doesn't have GPU device access."""
        containers = docker_client.containers.list(
            filters={"label": "com.docker.compose.service=comfy-cpu"}
        )
        assert len(containers) > 0, "No ComfyUI CPU containers found"

        container = containers[0]
        host_config = container.attrs['HostConfig']

        # CPU container should not have GPU device requests
        device_requests = host_config.get('DeviceRequests', [])
        assert len(device_requests) == 0, "CPU container should not have GPU devices"
