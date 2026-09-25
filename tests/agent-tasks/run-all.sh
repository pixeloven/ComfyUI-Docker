#!/usr/bin/env bash
# The full matrix: 3 servers x 4 tasks, one run.sh each. Pass HARNESS_RUN=1 to
# launch the agents; without it, every row is a dry run.
set -uo pipefail
here="$(dirname "$0")"
for server in comfy-mcp artokun joenorton; do
  for task in T1 T2 T3 T4; do
    echo "=== $server $task"
    "$here/run.sh" "$server" "$task" || echo "run.sh $server $task exited $?"
  done
done
