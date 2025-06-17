"""
Tests for ComfyUI CPU-only mode functionality.
"""
import pytest
import requests
import time
import subprocess
from pathlib import Path
import sys
import os

# Add the tests directory to the path so we can import conftest
sys.path.insert(0, os.path.dirname(__file__))
from conftest import run_docker_compose, wait_for_service


class TestComfyCPU:
    """Test class for ComfyUI CPU mode."""

    @pytest.fixture(scope="class", autouse=True)
    def setup_comfy_cpu(self, project_root, cleanup_containers):
        """Setup ComfyUI CPU service for testing."""
        # Build the CPU image
        build_result = run_docker_compose(
            ["build", "--no-cache"], 
            profile="comfy-cpu", 
            project_root=project_root
        )
        assert build_result.returncode == 0, f"Build failed: {build_result.stderr}"
        
        # Start the service
        start_result = run_docker_compose(
            ["up", "-d"], 
            profile="comfy-cpu", 
            project_root=project_root
        )
        assert start_result.returncode == 0, f"Start failed: {start_result.stderr}"
        
        # Wait for service to be ready
        service_ready = wait_for_service("http://localhost:8189", timeout=180)
        assert service_ready, "ComfyUI CPU service did not start within timeout"
        
        yield
        
        # Cleanup
        run_docker_compose(
            ["down"], 
            profile="comfy-cpu", 
            project_root=project_root
        )

    def test_cpu_service_health(self, comfy_cpu_service_url):
        """Test that ComfyUI CPU service is healthy and responding."""
        response = requests.get(comfy_cpu_service_url, timeout=30)
        assert response.status_code == 200
        assert "ComfyUI" in response.text

    def test_cpu_api_endpoints(self, comfy_cpu_service_url):
        """Test that essential API endpoints are available."""
        # Test system stats endpoint
        response = requests.get(f"{comfy_cpu_service_url}/system_stats", timeout=30)
        assert response.status_code == 200
        
        # Test queue endpoint
        response = requests.get(f"{comfy_cpu_service_url}/queue", timeout=30)
        assert response.status_code == 200

    def test_cpu_mode_cli_args(self, docker_client):
        """Test that CPU mode CLI arguments are set correctly."""
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

        cli_args = env_vars.get('CLI_ARGS', '')
        assert '--cpu' in cli_args, "CLI_ARGS should contain --cpu flag for CPU mode"

    def test_cpu_container_no_gpu_access(self, docker_client):
        """Test that CPU container doesn't have GPU access."""
        containers = docker_client.containers.list(
            filters={"label": "com.docker.compose.service=comfy-cpu"}
        )
        assert len(containers) > 0, "No ComfyUI CPU containers found"
        
        container = containers[0]
        host_config = container.attrs['HostConfig']
        
        # Check that no GPU devices are allocated
        device_requests = host_config.get('DeviceRequests', [])
        assert len(device_requests) == 0, "CPU container should not have GPU device requests"

    def test_unified_image_exists(self, docker_client):
        """Test that the unified image was built correctly."""
        try:
            image = docker_client.images.get("comfy:v0.3.39")
            assert image is not None, "Unified image should exist"

        except docker.errors.ImageNotFound:
            pytest.fail("ComfyUI unified image not found")

    @pytest.mark.slow
    def test_cpu_basic_workflow_execution(self, comfy_cpu_service_url):
        """Test basic workflow execution in CPU mode (if models are available)."""
        # This is a basic test that would require actual models
        # For now, just test that the workflow endpoint accepts requests
        workflow_data = {
            "prompt": {},
            "client_id": "test_client"
        }
        
        try:
            response = requests.post(
                f"{comfy_cpu_service_url}/prompt",
                json=workflow_data,
                timeout=30
            )
            # We expect this to fail without proper workflow, but should not be a connection error
            assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"
        except requests.exceptions.RequestException as e:
            pytest.fail(f"Failed to connect to workflow endpoint: {e}")

    def test_cpu_logs_contain_cpu_mode_indicator(self, docker_client):
        """Test that container logs indicate CPU mode is active."""
        containers = docker_client.containers.list(
            filters={"label": "com.docker.compose.service=comfy-cpu"}
        )
        assert len(containers) > 0, "No ComfyUI CPU containers found"
        
        container = containers[0]
        logs = container.logs(tail=100).decode('utf-8')
        
        assert "Running ComfyUI in CPU-only mode" in logs, "CPU mode indicator not found in logs"
