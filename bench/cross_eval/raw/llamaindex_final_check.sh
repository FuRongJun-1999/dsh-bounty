#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
set -u
R="$ROOT"
rm -rf /tmp/gc
echo "### 我的交付物"
ls -l $R/bench/cross_eval/systems/llamaindex_impl.py
ls -l $R/docs/reviews/LlamaIndex-Workflows_v0.1.md
echo "### raw/llamaindex_* 清单"
ls -1 $R/bench/cross_eval/raw/llamaindex_*
echo "### 仓库根目录越界文件复查"
ls -1 $R/_probe* 2>/dev/null || echo "  (none)"
echo "### 报告 sha256 / 行数"
sha256sum $R/docs/reviews/LlamaIndex-Workflows_v0.1.md
wc -l $R/docs/reviews/LlamaIndex-Workflows_v0.1.md
