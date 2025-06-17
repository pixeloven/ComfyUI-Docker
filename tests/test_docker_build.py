"""
Essential Docker build tests.
Focused on critical build validation for single developer maintenance.
"""
import pytest
import docker
import subprocess
from pathlib import Path
import sys
import os

# Add the tests directory to the path so we can import conftest
sys.path.insert(0, os.path.dirname(__file__))
from conftest import run_docker_compose


class TestDockerBuild:
    """Essential Docker build tests."""

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

    def test_image_has_required_packages(self, docker_client):
        """Test that image has essential packages installed."""
        try:
            image = docker_client.images.get("comfy:v0.3.39")

            # Check for onnxruntime-gpu (handles both GPU and CPU)
            container = docker_client.containers.run(
                image.id,
                command="pip list",
                remove=True,
                detach=False
            )

            output = container.decode('utf-8')
            assert "onnxruntime-gpu" in output, "Should have onnxruntime-gpu package"

        except docker.errors.ImageNotFound:
            pytest.skip("Image not available for testing")

    def test_dockerfile_syntax(self, project_root):
        """Test that Dockerfile has valid syntax."""
        dockerfile_path = project_root / "services" / "comfy" / "Dockerfile"
        assert dockerfile_path.exists(), "Dockerfile should exist"

        # Test building with syntax check
        result = subprocess.run([
            "docker", "build",
            "--file", str(dockerfile_path),
            "--tag", "test-syntax-check",
            str(dockerfile_path.parent)
        ], capture_output=True, text=True)

        assert result.returncode == 0, f"Dockerfile syntax error: {result.stderr}"

        # Cleanup
        try:
            docker_client = docker.from_env()
            docker_client.images.remove("test-syntax-check", force=True)
        except:
            pass

    def test_entrypoint_permissions(self, docker_client):
        """Test that entrypoint script is executable."""
        try:
            image = docker_client.images.get("comfy:v0.3.39")
            container = docker_client.containers.run(
                image.id,
                command="ls -la /home/comfy/app/entrypoint.sh",
                remove=True,
                detach=False
            )

            output = container.decode('utf-8')
            assert "rwx" in output, "entrypoint.sh should be executable"

        except docker.errors.ImageNotFound:
            pytest.skip("Image not available for testing")
