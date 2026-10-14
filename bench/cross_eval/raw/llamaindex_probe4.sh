#!/bin/bash
set -u
L=/home/ubuntu/dm/pylibs/llamaindex/workflows
echo "=== executor / to_thread / run_in_executor ==="
grep -rn "run_in_executor\|to_thread\|ThreadPoolExecutor\|ProcessPoolExecutor" $L/ | grep -v Binary | head -30
echo "=== num_workers usage ==="
grep -rn "num_workers" $L/ | head -30
echo "=== StepStateChanged ==="
sed -n '619,680p' $L/events.py
echo "=== workflow.py class Workflow 44-110 ==="
sed -n '44,110p' $L/workflow.py
