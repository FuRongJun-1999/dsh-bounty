#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
set -u
cd "$ROOT"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/llamaindex
mkdir -p bench/cross_eval/raw/llamaindex_walltime_tmp
echo "### 五模式一轮 runner 墙钟耗时（/usr/bin/time -f %e），输出落 raw/llamaindex_walltime_tmp/ 不覆盖正式 raw"
/usr/bin/time -f "WALL_SECONDS %e" /usr/bin/python3 -X utf8 bench/cross_eval/harness/runner.py \
  --impl bench/cross_eval/systems/llamaindex_impl.py \
  --name llamaindex \
  --modes normal,resume,retry,sequential,parallel \
  --rawdir bench/cross_eval/raw/llamaindex_walltime_tmp 2>&1 | tee bench/cross_eval/raw/llamaindex_walltime.txt
echo "WALLTIME_DONE"
