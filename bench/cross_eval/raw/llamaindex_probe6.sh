#!/bin/bash
set -u
L=/home/ubuntu/dm/pylibs/llamaindex/workflows
echo "=== is_fan_out ==="
grep -rn "is_fan_out" $L/ | head -20
echo "=== step_function.py 296-340 ==="
sed -n '296,345p' $L/runtime/types/step_function.py
echo "=== grep fan_out in decorators/representation ==="
grep -rn "fan_out\|FanOut" $L/decorators.py $L/representation/*.py 2>/dev/null | head -30
