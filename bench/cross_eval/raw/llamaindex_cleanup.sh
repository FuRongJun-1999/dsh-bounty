#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
set -u
cd "$ROOT"
echo "### 清理越界探针文件（仓库根目录 _probe*.sh）"
rm -f _probe_llamaindex.sh _probe2.sh _probe3.sh _probe4.sh _probe5.sh _probe6.sh
echo "剩余 _probe* 文件："
ls -1 _probe* 2>/dev/null || echo "  (none)"
echo "### 守卫自查：scripts/check_reviews.py"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/llamaindex
/usr/bin/python3 -X utf8 scripts/check_reviews.py 2>&1 | tee bench/cross_eval/raw/llamaindex_guard.txt
echo "GUARD_EXIT=${PIPESTATUS[0]}
