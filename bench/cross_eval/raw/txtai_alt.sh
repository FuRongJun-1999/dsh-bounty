#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
{
echo "### 交替计时：baseline 与 txtai 各 3 轮 normal（spec.md:39 要求交替进行）"
for i in 1 2 3; do
  echo "--- round $i : baseline ---"
  /usr/bin/python3 -X utf8 bench/cross_eval/harness/runner.py --impl bench/cross_eval/harness/baseline.py --name txtai_altbase_r$i --modes normal --repeats 7 2>&1 | grep -E '^(SHA|TIMING)'
  echo "--- round $i : txtai ---"
  /usr/bin/python3 -X utf8 bench/cross_eval/harness/runner.py --impl bench/cross_eval/systems/txtai_impl.py --name txtai_altself_r$i --modes normal --repeats 7 2>&1 | grep -E '^(SHA|TIMING)'
done
} 2>&1 | tee bench/cross_eval/raw/txtai_timing_alt.txt
