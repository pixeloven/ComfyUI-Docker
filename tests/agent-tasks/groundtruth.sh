#!/usr/bin/env bash
# Dump /object_info from the running instance into results/, with the pinned
# version and image digest beside it. Run after up.sh, before any task, so the
# dump describes built-in nodes only.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

curl -fsS "$COMFY_URL/object_info" -o "$RESULTS/object_info.json"
hpy record-instance "$HARNESS_IMAGE" > "$RESULTS/object_info.meta.json"
python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))), "node classes")' "$RESULTS/object_info.json"
cat "$RESULTS/object_info.meta.json"
