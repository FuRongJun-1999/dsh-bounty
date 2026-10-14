#!/bin/bash
set -u
W=/home/ubuntu/dm/pylibs/llamaindex/workflows
echo "=== runner.py 350-375 ==="
sed -n '350,375p' $W/runtime/control_loop/runner.py
echo "=== step_function.py 225-240 ==="
sed -n '225,240p' $W/runtime/types/step_function.py
echo "=== grep step name in error messages ==="
grep -rn "Step .* failed\|step_name}\|Step {.*} failed\|WorkflowRuntimeError(" $W/runtime/control_loop/runner.py $W/runtime/types/step_function.py | head -30
