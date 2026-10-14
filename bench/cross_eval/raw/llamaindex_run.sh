#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
set -u
cd "$ROOT"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/llamaindex
/usr/bin/python3 -X utf8 bench/cross_eval/harness/runner.py \
  --impl bench/cross_eval/systems/llamaindex_impl.py \
  --name llamaindex \
  --modes normal,resume,retry,sequential,parallel \
  2>&1 | tee bench/cross_eval/raw/llamaindex_runner.txt
echo "EXIT=$?"
