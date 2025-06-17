"""
Essential environment configuration tests.
Focused on critical configuration validation for single developer maintenance.
"""
import pytest
import subprocess
from pathlib import Path
import sys
import os

# Add the tests directory to the path so we can import conftest
sys.path.insert(0, os.path.dirname(__file__))


class TestEnvConfiguration:
    """Essential environment configuration tests."""

    def test_env_example_exists(self, project_root):
        """Test that .env.example file exists with required content."""
        env_example_path = project_root / ".env.example"
        assert env_example_path.exists(), ".env.example file should exist"

        content = env_example_path.read_text()
        assert "COMFY_CLI_ARGS" in content, "Should have COMFY_CLI_ARGS variable"
        assert "--cpu" in content, "Should have CPU mode example"

    def test_docker_compose_syntax(self, project_root):
        """Test that docker-compose.yml has valid syntax."""
        result = subprocess.run([
            "docker", "compose", "config", "--quiet"
        ], cwd=project_root, capture_output=True, text=True)

        assert result.returncode == 0, f"Docker compose syntax error: {result.stderr}"

    def test_service_profiles_exist(self, project_root):
        """Test that required service profiles are defined."""
        result = subprocess.run([
            "docker", "compose", "config", "--profiles"
        ], cwd=project_root, capture_output=True, text=True)

        assert result.returncode == 0, f"Profile check failed: {result.stderr}"

        profiles = result.stdout.strip().split('\n')
        assert "comfy" in profiles, "comfy profile should exist"
        assert "comfy-cpu" in profiles, "comfy-cpu profile should exist"

    def test_port_configuration(self, project_root):
        """Test that services use correct ports."""
        result = subprocess.run([
            "docker", "compose", "config"
        ], cwd=project_root, capture_output=True, text=True)

        assert result.returncode == 0, f"Config check failed: {result.stderr}"

        config_output = result.stdout
        assert "8188:8188" in config_output, "GPU service should use port 8188"
        assert "8189:8188" in config_output, "CPU service should use port 8189"

    def test_cli_args_examples(self, project_root):
        """Test that .env.example has essential CLI argument examples."""
        env_example_path = project_root / ".env.example"
        content = env_example_path.read_text()

        # Check for key CLI options
        essential_options = ["--cpu", "--lowvram"]
        for option in essential_options:
            assert option in content, f"Should have example for {option}"
