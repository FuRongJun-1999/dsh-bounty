#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
# cross-eval 分片 txtai：复跑命令（第三方可原样执行）
set -u
cd "$ROOT"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
python3 -X utf8 bench/cross_eval/harness/runner.py --impl bench/cross_eval/systems/txtai_impl.py --name txtai --modes normal,resume,retry,sequential,parallel 2>&1 | tee bench/cross_eval/raw/txtai_runner.txt
