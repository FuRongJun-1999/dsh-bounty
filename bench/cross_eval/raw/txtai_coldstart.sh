#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
{
echo "### 版本（顶层 txtai 不导出 __version__，用 importlib.metadata）"
/usr/bin/python3 -X utf8 -c "
import importlib.metadata as m
print('importlib.metadata.version(txtai)      =', m.version('txtai'))
print('importlib.metadata.version(torch)      =', m.version('torch'))
print('importlib.metadata.version(rank_bm25)  =', m.version('rank_bm25'))
print('importlib.metadata.version(numpy)      =', m.version('numpy'))
print('importlib.metadata.version(transformers) =', m.version('transformers'))
"
echo "### 每个新进程测 import 耗时（PYTHONPATH 已含 base+txtai），3 次取样"
for i in 1 2 3; do
  /usr/bin/python3 -X utf8 -c "
import time
t=time.perf_counter(); import txtai; a=(time.perf_counter()-t)*1000
print('sample=%d import_txtai_ms=%.1f' % ($i, a))
"
done
echo "### 对照：只 import torch（独立进程）"
for i in 1 2 3; do
  /usr/bin/python3 -X utf8 -c "
import time
t=time.perf_counter(); import torch; a=(time.perf_counter()-t)*1000
print('sample=%d import_torch_only_ms=%.1f' % ($i, a))
"
done
echo "### 对照：只 import rank_bm25+numpy（基线的依赖面，独立进程）"
for i in 1 2 3; do
  /usr/bin/python3 -X utf8 -c "
import time
t=time.perf_counter(); import rank_bm25, numpy; a=(time.perf_counter()-t)*1000
print('sample=%d import_rank_bm25_numpy_ms=%.1f' % ($i, a))
"
done
echo "### 对照：只 import 本方案真正用到的 txtai 子模块（txtai.workflow）"
for i in 1 2 3; do
  /usr/bin/python3 -X utf8 -c "
import time
t=time.perf_counter(); from txtai.workflow import Task, Workflow; a=(time.perf_counter()-t)*1000
print('sample=%d import_txtai_workflow_ms=%.1f' % ($i, a))
"
done
} 2>&1 | tee bench/cross_eval/raw/txtai_coldstart.txt
