#!/usr/bin/env bash
# PASS when results/T5.json names a template tagged "Image Upscale"; its job is
# a /history entry new since setup that completed with the template's nodes and
# settings (each node class as many times as the template has it, and every
# value set on a node one of the template's widget values for that class);
# every output the template declares saved a PNG to output/ at twice the
# input's size, and the report lists exactly those files; and comfyrelay's
# template_get, asked now, says that template is runnable, as the report does,
# and says a candidate that declares a model is not. Needs comfyrelay running.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t5
