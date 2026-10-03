#!/usr/bin/env bash
# PASS when results/T5.json names a template tagged "Image Upscale"; its job is
# a /history entry new since setup that completed with the template's nodes and
# settings (each node class as many times as the template has it, and every
# value set on a node one of the template's widget values for that class);
# every output the template declares saved a new PNG (not there at setup) to
# output/ at twice the input's size; the report lists exactly those files and
# says runnable. Then a relay self-test, reported separately: comfyrelay's
# template_get, asked now, says that template is runnable and a candidate that
# declares a model is not. It fails the task only when HARNESS_SERVER is
# comfyrelay (the default), and needs comfyrelay running.
set -euo pipefail
. "$(dirname "$0")/../../lib.sh"
hpy check t5
