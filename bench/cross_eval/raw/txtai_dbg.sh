#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
set -u
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
cd "$ROOT"
python3 -X utf8 - <<'PYEOF'
import sys, traceback
sys.path.insert(0, "bench/cross_eval/harness")
sys.path.insert(0, "bench/cross_eval/systems")
import txtai_impl as M

cfg = {"corpus": "bench/cross_eval/data/corpus.jsonl",
       "queries": "bench/cross_eval/data/queries.jsonl",
       "out": "/tmp/txtai_dbg_out.jsonl", "workers": 4, "k": 5}
run_ctx = M._Run(cfg)
els = M._elements(cfg)
print("elements", len(els), type(els[0]), els[0][2])
try:
    out = M._execute(run_ctx, els, True, 4)
    print("OK out", len(out), out[0])
except Exception:
    traceback.print_exc()
print("trace", run_ctx.trace)
print("counts", run_ctx.counts)
PYEOF
