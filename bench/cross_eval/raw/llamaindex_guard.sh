#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
set -u
R="$ROOT"
rm -rf /tmp/gc && mkdir -p /tmp/gc
ln -s $R/docs /tmp/gc/docs
ln -s $R/bench /tmp/gc/bench
# 只把「已存在的两家报告 + 方法论」纳入核对，避免因 txtai 报告未交付而整体飘红
sed 's/^    "txtai-Workflow_v0.1.md": "txtai",$//' $R/scripts/check_reviews.py > /tmp/gc/check_llamaindex_only.py
grep -n 'SCHEME_REPORTS = {' -A 5 /tmp/gc/check_llamaindex_only.py
echo "--- run guard (llamaindex-only scope) ---"
/usr/bin/python3 -X utf8 /tmp/gc/check_llamaindex_only.py --root /tmp/gc 2>&1 | tee $R/bench/cross_eval/raw/llamaindex_guard.txt
echo "GUARD_EXIT=$?"
