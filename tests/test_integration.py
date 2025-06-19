"""
Simple integration tests to verify services work together.
"""
import pytest
import requests
import sys
import os

# Add the tests directory to the path so we can import conftest
sys.path.insert(0, os.path.dirname(__file__))
from conftest import run_docker_compose, wait_for_service


class TestIntegration:
    """Test service integration."""

    def test_services_can_run_together(self, project_root, cleanup_containers):
        """Test that both CPU and GPU services can run at the same time."""
        # Start both services
        gpu_result = run_docker_compose(
            ["up", "-d"], profile="comfy", project_root=project_root
        )
        assert gpu_result.returncode == 0, f"GPU service failed: {gpu_result.stderr}"

        cpu_result = run_docker_compose(
            ["up", "-d"], profile="comfy-cpu", project_root=project_root
        )
        assert cpu_result.returncode == 0, f"CPU service failed: {cpu_result.stderr}"

        # Wait for both services
        gpu_ready = wait_for_service("http://localhost:8188", timeout=120)
        cpu_ready = wait_for_service("http://localhost:8189", timeout=120)

        assert gpu_ready, "GPU service should be ready"
        assert cpu_ready, "CPU service should be ready"

        # Test both endpoints respond
        gpu_response = requests.get("http://localhost:8188", timeout=30)
        cpu_response = requests.get("http://localhost:8189", timeout=30)

        assert gpu_response.status_code == 200
        assert cpu_response.status_code == 200

        # Cleanup
        run_docker_compose(["down"], project_root=project_root)
