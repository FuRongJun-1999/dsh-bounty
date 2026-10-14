#!/bin/bash
set -u
L=/home/ubuntu/dm/pylibs/llamaindex/workflows
echo "=== stop_after_attempt 680-720 ==="
sed -n '680,700p' $L/retry_policy.py
echo "=== ConstantDelayRetryPolicy 898-960 ==="
sed -n '898,960p' $L/retry_policy.py
echo "=== ctx.retry_info ==="
grep -n "retry_info\|def retry_number\|_retry" $L/context/context.py | head -20
echo "=== workflow.py 420-470 ==="
sed -n '418,470p' $L/workflow.py
echo "=== events.py StartEvent 315-340 ==="
sed -n '315,340p' $L/events.py
