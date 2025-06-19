"""
Simple tests to verify Docker images build correctly.
"""
import pytest
import docker
import sys
import os

# Add the tests directory to the path so we can import conftest
sys.path.insert(0, os.path.dirname(__file__))
from conftest import run_docker_compose


class TestDockerBuild:
    """Test Docker build functionality."""

    def test_image_builds_successfully(self, docker_client, project_root):
        """Test that the Docker image builds without errors."""
        build_result = run_docker_compose(
            ["build", "comfy"],
            project_root=project_root
        )
        assert build_result.returncode == 0, f"Build failed: {build_result.stderr}"

        # Verify image exists
        try:
            image = docker_client.images.get("comfy:v0.3.39")
            assert image is not None, "Image should be created"
        except docker.errors.ImageNotFound:
            pytest.fail("Image was not created")

    def test_dockerfile_exists(self, project_root):
        """Test that Dockerfile exists and is readable."""
        dockerfile_path = project_root / "services" / "comfy" / "Dockerfile"
        assert dockerfile_path.exists(), "Dockerfile should exist"

        # Should be able to read the file
        with open(dockerfile_path, 'r') as f:
            content = f.read()
        assert len(content) > 0, "Dockerfile should not be empty"
