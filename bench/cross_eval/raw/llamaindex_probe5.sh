#!/bin/bash
set -u
L=/home/ubuntu/dm/pylibs/llamaindex/workflows
echo "=== step_function.py 250-320 ==="
sed -n '250,320p' $L/runtime/types/step_function.py
echo "=== internal_state.py 835-870 ==="
sed -n '835,870p' $L/runtime/types/internal_state.py
