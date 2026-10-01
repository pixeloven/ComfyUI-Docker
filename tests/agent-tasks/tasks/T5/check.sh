#!/usr/bin/env bash
# PASS when results/T5.json names a template tagged "Image Upscale", its job is
# a /history entry new since setup that completed, ran only that template's
# nodes on its own input, and saved the template's declared output type at
# twice the input's size; and comfyrelay's template_get, asked now, says that
# template is runnable, as the report does. Needs comfyrelay still running.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t5
