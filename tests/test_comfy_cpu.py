"""
Simple tests to verify ComfyUI CPU service starts and runs correctly.
"""
import pytest
import requests
import sys
import os

# Add the tests directory to the path so we can import conftest
sys.path.insert(0, os.path.dirname(__file__))
from conftest import run_docker_compose, wait_for_service


class TestComfyCPU:
    """Test ComfyUI CPU service startup and basic functionality."""

    @pytest.fixture(scope="class", autouse=True)
    def setup_comfy_cpu(self, project_root, cleanup_containers):
        """Start ComfyUI CPU service for testing."""
        # Start the service
        result = run_docker_compose(
            ["up", "-d", "--build"],
            profile="comfy-cpu",
            project_root=project_root
        )
        assert result.returncode == 0, f"Failed to start service: {result.stderr}"

        # Wait for service to be ready
        service_ready = wait_for_service("http://localhost:8189", timeout=120)
        assert service_ready, "ComfyUI CPU service did not start"

        yield

        # Cleanup
        run_docker_compose(["down"], profile="comfy-cpu", project_root=project_root)

    def test_service_responds(self, comfy_cpu_service_url):
        """Test that the service responds to HTTP requests."""
        response = requests.get(comfy_cpu_service_url, timeout=30)
        assert response.status_code == 200
        assert "ComfyUI" in response.text

    def test_service_runs_in_cpu_mode(self, docker_client):
        """Test that the service is running in CPU mode."""
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
