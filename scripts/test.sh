#!/bin/bash

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TESTS_DIR="$PROJECT_ROOT/tests"

echo -e "${GREEN}ComfyUI Docker Test Runner${NC}"
echo "Project root: $PROJECT_ROOT"
echo "Tests directory: $TESTS_DIR"

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    print_error "Docker is not running. Please start Docker and try again."
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker >/dev/null 2>&1; then
    print_error "docker command not found. Please install Docker."
    exit 1
fi

# Change to project root
cd "$PROJECT_ROOT"

# Install test dependencies if needed
if [ ! -d "$TESTS_DIR/.venv" ]; then
    print_status "Creating virtual environment for tests..."
    python3 -m venv "$TESTS_DIR/.venv"
fi

print_status "Activating virtual environment and installing dependencies..."
source "$TESTS_DIR/.venv/bin/activate"
pip install -r "$TESTS_DIR/requirements.txt"

# Parse command line arguments
TEST_TYPE="${1:-all}"
VERBOSE="${2:-}"

case "$TEST_TYPE" in
    "build")
        print_status "Running Docker build tests..."
        pytest "$TESTS_DIR/test_docker_build.py" -v $VERBOSE
        ;;
    "cpu")
        print_status "Running ComfyUI CPU tests..."
        pytest "$TESTS_DIR/test_comfy_cpu.py" -v $VERBOSE
        ;;
    "gpu")
        print_status "Running ComfyUI GPU tests..."
        if command -v nvidia-smi >/dev/null 2>&1; then
            pytest "$TESTS_DIR/test_comfy_gpu.py" -v $VERBOSE
        else
            print_warning "NVIDIA GPU not detected. Skipping GPU tests."
        fi
        ;;
    "env")
        print_status "Running environment configuration tests..."
        pytest "$TESTS_DIR/test_env_configuration.py" -v $VERBOSE
        ;;
    "integration")
        print_status "Running integration tests..."
        pytest "$TESTS_DIR/test_integration.py" -v $VERBOSE
        ;;
    "all")
        print_status "Running all tests..."

        # Run build tests first
        print_status "1. Running Docker build tests..."
        pytest "$TESTS_DIR/test_docker_build.py" -v $VERBOSE

        # Run environment tests
        print_status "2. Running environment configuration tests..."
        pytest "$TESTS_DIR/test_env_configuration.py" -v $VERBOSE

        # Run CPU tests
        print_status "3. Running ComfyUI CPU tests..."
        pytest "$TESTS_DIR/test_comfy_cpu.py" -v $VERBOSE

        # Run GPU tests if GPU is available
        if command -v nvidia-smi >/dev/null 2>&1; then
            print_status "4. Running ComfyUI GPU tests..."
            pytest "$TESTS_DIR/test_comfy_gpu.py" -v $VERBOSE
        else
            print_warning "NVIDIA GPU not detected. Skipping GPU tests."
        fi

        # Run integration tests
        print_status "5. Running integration tests..."
        pytest "$TESTS_DIR/test_integration.py" -v $VERBOSE
        ;;
    "clean")
        print_status "Cleaning up test containers and images..."
        docker compose down --remove-orphans || true
        docker image prune -f || true
        print_status "Cleanup completed."
        exit 0
        ;;
    *)
        echo "Usage: $0 [build|cpu|gpu|env|integration|all|clean] [--verbose]"
        echo ""
        echo "Test types:"
        echo "  build       - Run Docker build tests only"
        echo "  cpu         - Run ComfyUI CPU mode tests only"
        echo "  gpu         - Run ComfyUI GPU mode tests only (requires NVIDIA GPU)"
        echo "  env         - Run environment configuration tests only"
        echo "  integration - Run integration tests only"
        echo "  all         - Run all tests (default)"
        echo "  clean       - Clean up test containers and images"
        echo ""
        echo "Options:"
        echo "  --verbose  - Enable verbose pytest output"
        exit 1
        ;;
esac

print_status "Tests completed successfully!"

# Cleanup
print_status "Cleaning up test containers..."
docker compose down --remove-orphans || true

print_status "All done!"
