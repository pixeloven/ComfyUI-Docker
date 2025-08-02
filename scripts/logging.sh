#!/bin/bash

# Logging Library for ComfyUI Docker Scripts
# Source this file in your scripts to access colored logging functions
# Usage: source "$(dirname "$0")/../logging.sh" || source ./scripts/logging.sh

# Color codes for logging
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Logging functions with colors
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if functions are being sourced correctly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "This file should be sourced, not executed directly."
    echo "Usage: source \"\$(dirname \"\$0\")/../logging.sh\""
    exit 1
fi 