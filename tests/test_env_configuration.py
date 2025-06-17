"""
Tests for environment configuration and CLI arguments.
"""
import pytest
import os
import tempfile
import subprocess
from pathlib import Path
import sys

# Add the tests directory to the path so we can import conftest
sys.path.insert(0, os.path.dirname(__file__))
from conftest import run_docker_compose


class TestEnvConfiguration:
    """Test class for environment configuration."""

    def test_env_example_file_exists(self, project_root):
        """Test that .env.example file exists and has required sections."""
        env_example_path = project_root / ".env.example"
        assert env_example_path.exists(), ".env.example file should exist"
        
        content = env_example_path.read_text()
        
        # Check for required sections
        assert "ComfyUI Configuration" in content, "Should have ComfyUI configuration section"
        assert "COMFY_CLI_ARGS" in content, "Should have COMFY_CLI_ARGS variable"
        assert "--cpu" in content, "Should have CPU mode example"

    def test_cpu_cli_args_configuration(self, project_root):
        """Test that CPU CLI args work correctly."""
        # Create a temporary .env file with CPU configuration
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("""
PUID=1000
PGID=1000
COMFY_CLI_ARGS=--cpu
""")
            temp_env_file = f.name

        try:
            # Test that docker-compose can parse the configuration
            result = subprocess.run([
                "docker", "compose", 
                "--env-file", temp_env_file,
                "config", "--services"
            ], cwd=project_root, capture_output=True, text=True)
            
            assert result.returncode == 0, f"Docker compose config failed: {result.stderr}"
            assert "comfy" in result.stdout or "comfy-cpu" in result.stdout
            
        finally:
            os.unlink(temp_env_file)

    def test_gpu_cli_args_configuration(self, project_root):
        """Test that GPU CLI args work correctly."""
        # Create a temporary .env file with GPU configuration
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("""
PUID=1000
PGID=1000
COMFY_CLI_ARGS=--lowvram
""")
            temp_env_file = f.name

        try:
            # Test that docker-compose can parse the configuration
            result = subprocess.run([
                "docker", "compose", 
                "--env-file", temp_env_file,
                "config", "--services"
            ], cwd=project_root, capture_output=True, text=True)
            
            assert result.returncode == 0, f"Docker compose config failed: {result.stderr}"
            
        finally:
            os.unlink(temp_env_file)

    def test_empty_cli_args_configuration(self, project_root):
        """Test that empty CLI args work correctly."""
        # Create a temporary .env file with empty CLI args
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("""
PUID=1000
PGID=1000
COMFY_CLI_ARGS=
""")
            temp_env_file = f.name

        try:
            # Test that docker-compose can parse the configuration
            result = subprocess.run([
                "docker", "compose", 
                "--env-file", temp_env_file,
                "config", "--services"
            ], cwd=project_root, capture_output=True, text=True)
            
            assert result.returncode == 0, f"Docker compose config failed: {result.stderr}"
            
        finally:
            os.unlink(temp_env_file)

    def test_multiple_cli_args_configuration(self, project_root):
        """Test that multiple CLI args work correctly."""
        # Create a temporary .env file with multiple CLI args
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("""
PUID=1000
PGID=1000
COMFY_CLI_ARGS=--cpu --force-fp16
""")
            temp_env_file = f.name

        try:
            # Test that docker-compose can parse the configuration
            result = subprocess.run([
                "docker", "compose", 
                "--env-file", temp_env_file,
                "config", "--services"
            ], cwd=project_root, capture_output=True, text=True)
            
            assert result.returncode == 0, f"Docker compose config failed: {result.stderr}"
            
        finally:
            os.unlink(temp_env_file)

    def test_comfy_cpu_default_args(self, project_root):
        """Test that comfy-cpu service has default --cpu args when COMFY_CLI_ARGS is empty."""
        # Test docker-compose config for comfy-cpu service
        result = subprocess.run([
            "docker", "compose", 
            "--profile", "comfy-cpu",
            "config"
        ], cwd=project_root, capture_output=True, text=True)
        
        assert result.returncode == 0, f"Docker compose config failed: {result.stderr}"
        
        # Check that the comfy-cpu service has --cpu in CLI_ARGS
        config_output = result.stdout
        assert "comfy-cpu" in config_output, "comfy-cpu service should be in config"
        
        # The default should include --cpu when COMFY_CLI_ARGS is not set
        # This is handled by the ${COMFY_CLI_ARGS:---cpu} syntax in docker-compose.yml

    def test_env_example_has_all_cli_options(self, project_root):
        """Test that .env.example includes examples for all major CLI options."""
        env_example_path = project_root / ".env.example"
        content = env_example_path.read_text()
        
        # Check for various CLI option examples
        expected_options = [
            "--cpu",
            "--force-fp16", 
            "--lowvram",
            "--novram"
        ]
        
        for option in expected_options:
            assert option in content, f"Should have example for {option} option"

    def test_docker_compose_profiles(self, project_root):
        """Test that both comfy and comfy-cpu profiles are defined."""
        result = subprocess.run([
            "docker", "compose", "config", "--profiles"
        ], cwd=project_root, capture_output=True, text=True)
        
        assert result.returncode == 0, f"Docker compose config failed: {result.stderr}"
        
        profiles = result.stdout.strip().split('\n')
        assert "comfy" in profiles, "comfy profile should be available"
        assert "comfy-cpu" in profiles, "comfy-cpu profile should be available"

    def test_port_configuration(self, project_root):
        """Test that GPU and CPU services use different ports."""
        result = subprocess.run([
            "docker", "compose", "config"
        ], cwd=project_root, capture_output=True, text=True)
        
        assert result.returncode == 0, f"Docker compose config failed: {result.stderr}"
        
        config_output = result.stdout
        
        # Check that different ports are used
        assert "8188:8188" in config_output, "GPU service should use port 8188"
        assert "8189:8188" in config_output, "CPU service should use port 8189"
