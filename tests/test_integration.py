"""
Integration tests for ComfyUI Docker setup.
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


class TestIntegration:
    """Integration tests for both CPU and GPU modes."""

    def test_both_services_can_run_simultaneously(self, project_root, cleanup_containers):
        """Test that both CPU and GPU services can run at the same time."""
        # Build both images
        build_gpu = run_docker_compose(
            ["build"], profile="comfy", project_root=project_root
        )
        assert build_gpu.returncode == 0, f"GPU build failed: {build_gpu.stderr}"
        
        build_cpu = run_docker_compose(
            ["build"], profile="comfy-cpu", project_root=project_root
        )
        assert build_cpu.returncode == 0, f"CPU build failed: {build_cpu.stderr}"
        
        # Start both services
        start_gpu = run_docker_compose(
            ["up", "-d"], profile="comfy", project_root=project_root
        )
        assert start_gpu.returncode == 0, f"GPU start failed: {start_gpu.stderr}"
        
        start_cpu = run_docker_compose(
            ["up", "-d"], profile="comfy-cpu", project_root=project_root
        )
        assert start_cpu.returncode == 0, f"CPU start failed: {start_cpu.stderr}"
        
        # Wait for both services
        gpu_ready = wait_for_service("http://localhost:8188", timeout=120)
        cpu_ready = wait_for_service("http://localhost:8189", timeout=120)
        
        assert gpu_ready, "GPU service should be ready"
        assert cpu_ready, "CPU service should be ready"
        
        # Test both endpoints
        gpu_response = requests.get("http://localhost:8188", timeout=30)
        cpu_response = requests.get("http://localhost:8189", timeout=30)
        
        assert gpu_response.status_code == 200
        assert cpu_response.status_code == 200
        assert "ComfyUI" in gpu_response.text
        assert "ComfyUI" in cpu_response.text
        
        # Cleanup
        run_docker_compose(["down"], project_root=project_root)

    def test_service_switching(self, project_root, cleanup_containers):
        """Test switching between GPU and CPU services."""
        # Start GPU service
        build_result = run_docker_compose(
            ["build"], profile="comfy", project_root=project_root
        )
        assert build_result.returncode == 0
        
        start_result = run_docker_compose(
            ["up", "-d"], profile="comfy", project_root=project_root
        )
        assert start_result.returncode == 0
        
        # Wait for GPU service
        gpu_ready = wait_for_service("http://localhost:8188", timeout=120)
        assert gpu_ready, "GPU service should start"
        
        # Stop GPU service
        stop_result = run_docker_compose(
            ["down"], profile="comfy", project_root=project_root
        )
        assert stop_result.returncode == 0
        
        # Start CPU service
        build_result = run_docker_compose(
            ["build"], profile="comfy-cpu", project_root=project_root
        )
        assert build_result.returncode == 0
        
        start_result = run_docker_compose(
            ["up", "-d"], profile="comfy-cpu", project_root=project_root
        )
        assert start_result.returncode == 0
        
        # Wait for CPU service
        cpu_ready = wait_for_service("http://localhost:8189", timeout=120)
        assert cpu_ready, "CPU service should start"
        
        # Cleanup
        run_docker_compose(["down"], project_root=project_root)

    def test_data_persistence_between_modes(self, project_root, test_data_dir, cleanup_containers):
        """Test that data persists when switching between CPU and GPU modes."""
        # Create a test file in the data directory
        test_file = test_data_dir / "test_persistence.txt"
        test_content = "This is a test file for persistence"
        test_file.write_text(test_content)
        
        # Start GPU service
        build_result = run_docker_compose(
            ["build"], profile="comfy", project_root=project_root
        )
        assert build_result.returncode == 0
        
        start_result = run_docker_compose(
            ["up", "-d"], profile="comfy", project_root=project_root
        )
        assert start_result.returncode == 0
        
        gpu_ready = wait_for_service("http://localhost:8188", timeout=120)
        assert gpu_ready
        
        # Stop GPU and start CPU
        run_docker_compose(["down"], profile="comfy", project_root=project_root)
        
        build_result = run_docker_compose(
            ["build"], profile="comfy-cpu", project_root=project_root
        )
        assert build_result.returncode == 0
        
        start_result = run_docker_compose(
            ["up", "-d"], profile="comfy-cpu", project_root=project_root
        )
        assert start_result.returncode == 0
        
        cpu_ready = wait_for_service("http://localhost:8189", timeout=120)
        assert cpu_ready
        
        # Verify test file still exists
        assert test_file.exists(), "Test file should persist between mode switches"
        assert test_file.read_text() == test_content, "Test file content should be unchanged"
        
        # Cleanup
        run_docker_compose(["down"], project_root=project_root)
        test_file.unlink(missing_ok=True)

    def test_makefile_targets(self, project_root):
        """Test that Makefile targets work correctly."""
        makefile_path = project_root / "Makefile"
        assert makefile_path.exists(), "Makefile should exist"
        
        # Test help target
        result = subprocess.run(
            ["make", "help"], 
            cwd=project_root, 
            capture_output=True, 
            text=True
        )
        assert result.returncode == 0, "make help should work"
        assert "ComfyUI Docker Management" in result.stdout
        
        # Test config target
        result = subprocess.run(
            ["make", "config"], 
            cwd=project_root, 
            capture_output=True, 
            text=True
        )
        assert result.returncode == 0, "make config should work"

    def test_script_permissions(self, project_root):
        """Test that scripts have correct permissions."""
        test_script = project_root / "scripts" / "test.sh"
        assert test_script.exists(), "test.sh should exist"
        
        # Check if script is executable
        import stat
        file_stat = test_script.stat()
        is_executable = bool(file_stat.st_mode & stat.S_IEXEC)
        assert is_executable, "test.sh should be executable"

    @pytest.mark.slow
    def test_full_workflow_cpu_mode(self, project_root, cleanup_containers):
        """Test a complete workflow in CPU mode (basic API test)."""
        # Build and start CPU service
        build_result = run_docker_compose(
            ["build"], profile="comfy-cpu", project_root=project_root
        )
        assert build_result.returncode == 0
        
        start_result = run_docker_compose(
            ["up", "-d"], profile="comfy-cpu", project_root=project_root
        )
        assert start_result.returncode == 0
        
        # Wait for service
        service_ready = wait_for_service("http://localhost:8189", timeout=180)
        assert service_ready, "CPU service should be ready"
        
        # Test basic API endpoints
        base_url = "http://localhost:8189"
        
        # Test system stats
        response = requests.get(f"{base_url}/system_stats", timeout=30)
        assert response.status_code == 200
        
        # Test queue
        response = requests.get(f"{base_url}/queue", timeout=30)
        assert response.status_code == 200
        
        # Test object info (available models/nodes)
        response = requests.get(f"{base_url}/object_info", timeout=30)
        assert response.status_code == 200
        
        # Cleanup
        run_docker_compose(["down"], project_root=project_root)
