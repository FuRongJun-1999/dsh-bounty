#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
set -u
cd "$ROOT"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/llamaindex
{
echo "### M8-1 依赖足迹 du -sh（隔离 --target 目录）"
du -sh /home/ubuntu/dm/pylibs/base
du -sh /home/ubuntu/dm/pylibs/llamaindex
echo "### M8-2 引擎发行版（dist-info 目录名 = 实际安装版本）"
ls -d /home/ubuntu/dm/pylibs/llamaindex/llama_index_*.dist-info
ls -d /home/ubuntu/dm/pylibs/base/rank_bm25-*.dist-info /home/ubuntu/dm/pylibs/base/numpy-*.dist-info
echo "### M8-3/4 python 证据"
/usr/bin/python3 -X utf8 bench/cross_eval/raw/llamaindex_m8.py
} 2>&1 | tee bench/cross_eval/raw/llamaindex_m8.txt
echo "M8_SH_DONE"
