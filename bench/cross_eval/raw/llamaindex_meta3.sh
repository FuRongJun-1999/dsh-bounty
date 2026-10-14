#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
set -u
echo "=== engine dist-info ==="
ls -d /home/ubuntu/dm/pylibs/llamaindex/llama_index* 2>/dev/null | sed 's#.*/##'
echo "=== workflows dist-info ==="
ls -d /home/ubuntu/dm/pylibs/llamaindex/workflows-*.dist-info /home/ubuntu/dm/pylibs/llamaindex/llama_index_workflows* 2>/dev/null | sed 's#.*/##'
echo "=== base key dist-info ==="
ls -d /home/ubuntu/dm/pylibs/base/rank_bm25* /home/ubuntu/dm/pylibs/base/numpy* 2>/dev/null | sed 's#.*/##'
echo "=== META head ==="
head -n 8 "$ROOT"/bench/cross_eval/raw/llamaindex_meta.txt
echo "=== META tail 25 ==="
tail -n 25 "$ROOT"/bench/cross_eval/raw/llamaindex_meta.txt
