#!/usr/bin/env bash
set -u
T=/home/ubuntu/dm/pylibs/txtai/txtai
echo "=== grep concurrency ==="
grep -rn 'concurrency' "$T" | head -40
echo "=== grep checkpoint (workflow) ==="
grep -rni 'checkpoint' "$T/workflow/" | head -20
echo "=== grep retry/backoff (workflow) ==="
grep -rni -e 'retry' -e 'retries' -e 'backoff' "$T/workflow/" | head -20
echo "=== grep resume/restart (workflow) ==="
grep -rni -e 'resume' -e 'restart' "$T/workflow/" | head -20
echo "=== task/__init__.py ==="
cat -n "$T/workflow/task/__init__.py"
echo "=== task/factory.py ==="
cat -n "$T/workflow/task/factory.py"
