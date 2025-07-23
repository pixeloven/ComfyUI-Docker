#!/bin/bash
set -e

# Run post install script
./post_install.sh

exec "$@"
