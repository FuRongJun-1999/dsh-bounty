#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
{
echo "### du -sh 依赖足迹"
du -sh /home/ubuntu/dm/pylibs/txtai
du -sh /home/ubuntu/dm/pylibs/base
du -sh /home/ubuntu/dm/pylibs/txtai/txtai
du -sh /home/ubuntu/dm/pylibs/txtai/torch
du -sh /home/ubuntu/dm/pylibs/txtai/nvidia 2>/dev/null
du -sh /home/ubuntu/dm/pylibs/base/rank_bm25 /home/ubuntu/dm/pylibs/base/numpy 2>/dev/null
echo "### 只算本方案真正 import 到的包（txtai 自身 + torch + transformers/huggingface_hub）"
du -sh /home/ubuntu/dm/pylibs/txtai/txtai /home/ubuntu/dm/pylibs/txtai/torch /home/ubuntu/dm/pylibs/txtai/transformers /home/ubuntu/dm/pylibs/txtai/huggingface_hub 2>/dev/null
echo "### 顶层目录清单（前 20，按大小）"
du -sh /home/ubuntu/dm/pylibs/txtai/* 2>/dev/null | sort -rh | head -20
} 2>&1 | tee bench/cross_eval/raw/txtai_du.txt
