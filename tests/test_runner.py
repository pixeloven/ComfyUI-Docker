#!/usr/bin/env python3
"""
ComfyUI Docker Test Runner - Phase 1
Drop-in replacement for bash test script with same CLI interface.
"""
import sys
import subprocess
import time
from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import track
import docker


class TestRunner:
    """Main test runner class."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.console = Console()

        # Handle both local and containerized environments
        if 'PROJECT_ROOT' in os.environ:
            self.project_root = Path(os.environ['PROJECT_ROOT'])
        else:
            self.project_root = Path(__file__).parent.parent

        if 'TESTS_DIR' in os.environ:
            self.tests_dir = Path(os.environ['TESTS_DIR'])
        else:
            self.tests_dir = self.project_root / "tests"

        # Initialize Docker client
        try:
            self.docker_client = docker.from_env()
        except docker.errors.DockerException as e:
            self.console.print(f"[red]❌ Docker not available: {e}[/red]")
            sys.exit(1)
    
    def print_status(self, message: str):
        """Print status message with formatting."""
        self.console.print(f"[blue]🔍 {message}[/blue]")
    
    def print_success(self, message: str):
        """Print success message."""
        self.console.print(f"[green]✅ {message}[/green]")
    
    def print_error(self, message: str):
        """Print error message."""
        self.console.print(f"[red]❌ {message}[/red]")
    
    def print_warning(self, message: str):
        """Print warning message."""
        self.console.print(f"[yellow]⚠️  {message}[/yellow]")
    
    def run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> bool:
        """Run a command and return success status."""
        if self.verbose:
            self.console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or self.project_root,
                capture_output=not self.verbose,
                text=True,
                check=False
            )
            return result.returncode == 0
        except Exception as e:
            self.print_error(f"Command failed: {e}")
            return False
    
    def run_pytest(self, test_file: str) -> bool:
        """Run pytest on a specific test file."""
        test_path = self.tests_dir / test_file
        if not test_path.exists():
            self.print_error(f"Test file not found: {test_path}")
            return False

        cmd = ["python3", "-m", "pytest", str(test_path), "-v"]
        if self.verbose:
            cmd.extend(["--tb=short", "-s"])

        return self.run_command(cmd)
    
    def check_gpu_available(self) -> bool:
        """Check if NVIDIA GPU is available."""
        return self.run_command(["nvidia-smi"], cwd=None)
    
    def run_build_tests(self) -> bool:
        """Run Docker build tests."""
        self.print_status("Running Docker build tests...")
        return self.run_pytest("test_docker_build.py")
    
    def run_env_tests(self) -> bool:
        """Run environment configuration tests."""
        self.print_status("Running environment configuration tests...")
        return self.run_pytest("test_env_configuration.py")
    
    def run_cpu_tests(self) -> bool:
        """Run ComfyUI CPU tests."""
        self.print_status("Running ComfyUI CPU tests...")
        return self.run_pytest("test_comfy_cpu.py")
    
    def run_gpu_tests(self) -> bool:
        """Run ComfyUI GPU tests."""
        if not self.check_gpu_available():
            self.print_warning("NVIDIA GPU not detected. Skipping GPU tests.")
            return True
        
        self.print_status("Running ComfyUI GPU tests...")
        return self.run_pytest("test_comfy_gpu.py")
    
    def run_integration_tests(self) -> bool:
        """Run integration tests."""
        self.print_status("Running integration tests...")
        return self.run_pytest("test_integration.py")
    
    def run_all_tests(self) -> bool:
        """Run all essential tests."""
        self.console.print(Panel("Running Essential Test Suite", style="blue"))
        
        tests = [
            ("Build validation", self.run_build_tests),
            ("Environment configuration", self.run_env_tests),
            ("CPU functionality", self.run_cpu_tests),
            ("GPU functionality", self.run_gpu_tests),
            ("Integration", self.run_integration_tests),
        ]
        
        results = []
        for test_name, test_func in tests:
            self.print_status(f"Running {test_name.lower()} tests...")
            success = test_func()
            results.append((test_name, success))
            
            if success:
                self.print_success(f"{test_name} tests passed")
            else:
                self.print_error(f"{test_name} tests failed")
        
        # Summary
        self.console.print("\n" + "="*50)
        self.console.print("[bold]Test Results Summary:[/bold]")
        
        all_passed = True
        for test_name, success in results:
            status = "✅ PASS" if success else "❌ FAIL"
            color = "green" if success else "red"
            self.console.print(f"[{color}]{status}[/{color}] {test_name}")
            if not success:
                all_passed = False
        
        if all_passed:
            self.print_success("All tests passed! 🎉")
        else:
            self.print_error("Some tests failed. Check output above for details.")
        
        return all_passed


@click.command()
@click.argument('test_type', type=click.Choice(['all', 'build', 'env', 'cpu', 'gpu', 'integration']))
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
def main(test_type: str, verbose: bool):
    """
    ComfyUI Docker Test Runner
    
    TEST_TYPE: Type of tests to run (all, build, env, cpu, gpu, integration)
    """
    runner = TestRunner(verbose=verbose)
    
    # Map test types to methods
    test_methods = {
        'all': runner.run_all_tests,
        'build': runner.run_build_tests,
        'env': runner.run_env_tests,
        'cpu': runner.run_cpu_tests,
        'gpu': runner.run_gpu_tests,
        'integration': runner.run_integration_tests,
    }
    
    try:
        success = test_methods[test_type]()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        runner.print_warning("Tests interrupted by user")
        sys.exit(130)
    except Exception as e:
        runner.print_error(f"Unexpected error: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
