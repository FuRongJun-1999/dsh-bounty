#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
set -u
cd "$ROOT"
OUT=bench/cross_eval/raw/llamaindex_meta.txt
{
echo "### M8 引擎发行版（dist-info 目录名，实际安装）"
ls -d /home/ubuntu/dm/pylibs/llamaindex/*.dist-info
echo "### M8 rank_bm25 / numpy（base target）"
ls -d /home/ubuntu/dm/pylibs/base/*.dist-info | grep -Ei 'rank|numpy'
echo "### M8 python 与平台"
/usr/bin/python3 -VV
uname -srmo
echo "### M8 pip 安装来源（本方案未额外安装任何包）"
ls /home/ubuntu/dm/pylibs/llamaindex/ | head -40
} >> $OUT 2>&1
tail -n 30 $OUT
echo "--- raw 目录 ---"
ls -la bench/cross_eval/raw/llamaindex_*
