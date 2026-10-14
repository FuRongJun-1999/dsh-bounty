#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
set -u
cd "$ROOT"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/llamaindex
/usr/bin/python3 -X utf8 bench/cross_eval/raw/llamaindex_meta.py 2>&1 | tee bench/cross_eval/raw/llamaindex_meta.txt
echo "EXIT=$?"
