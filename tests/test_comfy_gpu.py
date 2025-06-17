"""
Tests for ComfyUI GPU mode functionality.
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


class TestComfyGPU:
    """Test class for ComfyUI GPU mode."""

    @pytest.fixture(scope="class", autouse=True)
    def setup_comfy_gpu(self, project_root, cleanup_containers):
        """Setup ComfyUI GPU service for testing."""
        # Build the GPU image
        build_result = run_docker_compose(
            ["build", "--no-cache"], 
            profile="comfy", 
            project_root=project_root
        )
        assert build_result.returncode == 0, f"Build failed: {build_result.stderr}"
        
        # Start the service
        start_result = run_docker_compose(
            ["up", "-d"], 
            profile="comfy", 
            project_root=project_root
        )
        assert start_result.returncode == 0, f"Start failed: {start_result.stderr}"
        
        # Wait for service to be ready
        service_ready = wait_for_service("http://localhost:8188", timeout=180)
        assert service_ready, "ComfyUI GPU service did not start within timeout"
        
        yield
        
        # Cleanup
        run_docker_compose(
            ["down"], 
            profile="comfy", 
            project_root=project_root
        )

    def test_gpu_service_health(self, comfy_service_url):
        """Test that ComfyUI GPU service is healthy and responding."""
        response = requests.get(comfy_service_url, timeout=30)
        assert response.status_code == 200
        assert "ComfyUI" in response.text

    def test_gpu_api_endpoints(self, comfy_service_url):
        """Test that essential API endpoints are available."""
        # Test system stats endpoint
        response = requests.get(f"{comfy_service_url}/system_stats", timeout=30)
        assert response.status_code == 200
        
        # Test queue endpoint
        response = requests.get(f"{comfy_service_url}/queue", timeout=30)
        assert response.status_code == 200

    @pytest.mark.skipif(
        not any(line.strip() for line in subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True
        ).stdout.split('\n') if 'NVIDIA' in line),
        reason="No NVIDIA GPU available"
    )
    def test_gpu_mode_cli_args(self, docker_client):
        """Test that GPU mode CLI arguments are set correctly."""
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

        cli_args = env_vars.get('CLI_ARGS', '')
        # In GPU mode, CLI_ARGS should not contain --cpu flag by default
        assert '--cpu' not in cli_args, "CLI_ARGS should not contain --cpu flag in GPU mode"

    @pytest.mark.skipif(
        not any(line.strip() for line in subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True
        ).stdout.split('\n') if 'NVIDIA' in line),
        reason="No NVIDIA GPU available"
    )
    def test_gpu_container_has_gpu_access(self, docker_client):
        """Test that GPU container has GPU access configured."""
        containers = docker_client.containers.list(
            filters={"label": "com.docker.compose.service=comfy"}
        )
        assert len(containers) > 0, "No ComfyUI GPU containers found"
        
        container = containers[0]
        host_config = container.attrs['HostConfig']
        
        # Check that GPU devices are allocated
        device_requests = host_config.get('DeviceRequests', [])
        assert len(device_requests) > 0, "GPU container should have GPU device requests"
        
        # Check for NVIDIA driver
        nvidia_request = next(
            (req for req in device_requests if req.get('Driver') == 'nvidia'), 
            None
        )
        assert nvidia_request is not None, "Should have NVIDIA device request"

    def test_unified_image_exists(self, docker_client):
        """Test that the unified image was built correctly."""
        try:
            image = docker_client.images.get("comfy:v0.3.39")
            assert image is not None, "Unified image should exist"

        except docker.errors.ImageNotFound:
            pytest.fail("ComfyUI unified image not found")

    @pytest.mark.slow
    def test_gpu_basic_workflow_execution(self, comfy_service_url):
        """Test basic workflow execution in GPU mode (if models are available)."""
        # This is a basic test that would require actual models
        # For now, just test that the workflow endpoint accepts requests
        workflow_data = {
            "prompt": {},
            "client_id": "test_client"
        }
        
        try:
            response = requests.post(
                f"{comfy_service_url}/prompt",
                json=workflow_data,
                timeout=30
            )
            # We expect this to fail without proper workflow, but should not be a connection error
            assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"
        except requests.exceptions.RequestException as e:
            pytest.fail(f"Failed to connect to workflow endpoint: {e}")

    def test_gpu_logs_contain_gpu_mode_indicator(self, docker_client):
        """Test that container logs indicate GPU mode is active."""
        containers = docker_client.containers.list(
            filters={"label": "com.docker.compose.service=comfy"}
        )
        assert len(containers) > 0, "No ComfyUI GPU containers found"
        
        container = containers[0]
        logs = container.logs(tail=100).decode('utf-8')
        
        assert "Running ComfyUI in GPU mode" in logs, "GPU mode indicator not found in logs"

    @pytest.mark.skipif(
        not any(line.strip() for line in subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True
        ).stdout.split('\n') if 'NVIDIA' in line),
        reason="No NVIDIA GPU available"
    )
    def test_gpu_nvidia_runtime_available(self, docker_client):
        """Test that NVIDIA runtime is available in the container."""
        containers = docker_client.containers.list(
            filters={"label": "com.docker.compose.service=comfy"}
        )
        assert len(containers) > 0, "No ComfyUI GPU containers found"
        
        container = containers[0]
        
        # Execute nvidia-smi inside the container to verify GPU access
        try:
            exec_result = container.exec_run("nvidia-smi", timeout=30)
            assert exec_result.exit_code == 0, "nvidia-smi should work in GPU container"
            assert b"NVIDIA" in exec_result.output, "nvidia-smi output should contain NVIDIA"
        except Exception as e:
            pytest.fail(f"Failed to run nvidia-smi in container: {e}")
