"""
Simple tests to verify configuration files are correct.
"""
import pytest
import subprocess
from pathlib import Path
import sys
import os

# Add the tests directory to the path so we can import conftest
sys.path.insert(0, os.path.dirname(__file__))


class TestEnvConfiguration:
    """Test environment configuration."""

    def test_env_example_exists(self, project_root):
        """Test that .env.example file exists."""
        env_example_path = project_root / ".env.example"
        assert env_example_path.exists(), ".env.example file should exist"

        content = env_example_path.read_text()
        assert "COMFY_CLI_ARGS" in content, "Should have COMFY_CLI_ARGS variable"

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
