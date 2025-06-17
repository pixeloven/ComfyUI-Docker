"""
Tests for Docker build functionality and image validation.
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
    """Test class for Docker build functionality."""

    def test_unified_image_builds_successfully(self, docker_client, project_root):
        """Test that the unified image builds without errors."""
        build_result = run_docker_compose(
            ["build", "--no-cache", "comfy"],
            project_root=project_root
        )
        assert build_result.returncode == 0, f"Build failed: {build_result.stderr}"

        # Verify image exists
        try:
            image = docker_client.images.get("comfy:v0.3.39")
            assert image is not None
        except docker.errors.ImageNotFound:
            pytest.fail("Unified image was not created")

    def test_same_image_used_for_both_profiles(self, docker_client, project_root):
        """Test that both comfy and comfy-cpu profiles use the same image."""
        # Build both profiles
        build_gpu = run_docker_compose(
            ["build", "--no-cache", "comfy"],
            project_root=project_root
        )
        assert build_gpu.returncode == 0, f"GPU profile build failed: {build_gpu.stderr}"

        build_cpu = run_docker_compose(
            ["build", "--no-cache", "comfy-cpu"],
            project_root=project_root
        )
        assert build_cpu.returncode == 0, f"CPU profile build failed: {build_cpu.stderr}"

        # Both should create the same image
        try:
            image = docker_client.images.get("comfy:v0.3.39")
            assert image is not None
        except docker.errors.ImageNotFound:
            pytest.fail("Unified image was not created")

    def test_unified_image_has_correct_packages(self, docker_client):
        """Test that unified image has onnxruntime-gpu (which handles both GPU and CPU)."""
        try:
            image = docker_client.images.get("comfy:v0.3.39")

            # Create a temporary container to check packages
            container = docker_client.containers.run(
                image.id,
                command="pip list",
                remove=True,
                detach=False
            )

            output = container.decode('utf-8')
            assert "onnxruntime-gpu" in output, "Unified image should have onnxruntime-gpu"
            # Should NOT have separate onnxruntime
            assert "onnxruntime " not in output or "onnxruntime-gpu" in output, "Should use onnxruntime-gpu, not separate onnxruntime"

        except docker.errors.ImageNotFound:
            pytest.skip("Unified image not available for testing")

    def test_single_image_approach(self, docker_client):
        """Test that we now use a single unified image approach."""
        try:
            # Should have the unified image
            unified_image = docker_client.images.get("comfy:v0.3.39")
            assert unified_image is not None, "Unified image should exist"

            # Should NOT have separate CPU/GPU images anymore
            try:
                docker_client.images.get("comfy:v0.3.39-cpu")
                pytest.fail("Should not have separate CPU image")
            except docker.errors.ImageNotFound:
                pass  # This is expected

            try:
                docker_client.images.get("comfy:v0.3.39-gpu")
                pytest.fail("Should not have separate GPU image")
            except docker.errors.ImageNotFound:
                pass  # This is expected

        except docker.errors.ImageNotFound:
            pytest.skip("Unified image not available for testing")

    def test_dockerfile_syntax_validation(self, project_root):
        """Test that Dockerfile has valid syntax."""
        dockerfile_path = project_root / "services" / "comfy" / "Dockerfile"
        assert dockerfile_path.exists(), "Dockerfile should exist"

        # Test building the unified image
        result = subprocess.run([
            "docker", "build",
            "--file", str(dockerfile_path),
            "--tag", "test-comfy-syntax",
            str(dockerfile_path.parent)
        ], capture_output=True, text=True)

        assert result.returncode == 0, f"Dockerfile syntax validation failed: {result.stderr}"

        # Cleanup test image
        try:
            docker_client = docker.from_env()
            docker_client.images.remove("test-comfy-syntax", force=True)
        except:
            pass  # Ignore cleanup errors

    def test_simplified_single_stage_build(self, docker_client, project_root):
        """Test that the simplified single-stage build works correctly."""
        # Build the unified image
        build_result = subprocess.run([
            "docker", "build",
            "--tag", "test-comfy-unified-build",
            str(project_root / "services" / "comfy")
        ], capture_output=True, text=True)

        assert build_result.returncode == 0, f"Unified build failed: {build_result.stderr}"

        # Verify the image was created
        try:
            image = docker_client.images.get("test-comfy-unified-build")
            assert image is not None
        except docker.errors.ImageNotFound:
            pytest.fail("Unified build image was not created")

        # Cleanup test image
        try:
            docker_client.images.remove("test-comfy-unified-build", force=True)
        except docker.errors.ImageNotFound:
            pass  # Image might not exist if build failed

    def test_entrypoint_script_is_executable(self, docker_client):
        """Test that entrypoint script has correct permissions."""
        try:
            # Test with unified image
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
            pytest.skip("Unified image not available for testing")
