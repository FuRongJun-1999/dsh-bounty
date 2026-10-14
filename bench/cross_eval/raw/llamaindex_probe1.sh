#!/bin/bash
set -u
L=/home/ubuntu/dm/pylibs/llamaindex/workflows
echo "=== retry_policy factory 853-960 ==="
sed -n '853,905p' $L/retry_policy.py
echo "=== all public names in retry_policy ==="
grep -n "^def \|^class " $L/retry_policy.py | grep -v "^.*:class _"
echo "=== collect_events 446-540 ==="
sed -n '446,535p' $L/context/context.py
