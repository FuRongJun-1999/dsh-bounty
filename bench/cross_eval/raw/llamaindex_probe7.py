# -*- coding: utf-8 -*-
"""冒烟探针：直接调 run() 跑五个模式，检查契约字段与引擎能力是否真的生效。"""
import json
import os
import sys
import time

import os as _os_path
_ROOT = _os_path.path.abspath(_os_path.path.join(
    _os_path.path.dirname(_os_path.path.abspath(__file__)), "..", "..", ".."))

sys.path.insert(0, _os_path.path.join(_ROOT, "bench", "cross_eval", "harness"))
sys.path.insert(0, _os_path.path.join(_ROOT, "bench", "cross_eval", "systems"))

import metrics
import llamaindex_impl as impl

BASE = _os_path.path.join(_ROOT, "bench", "cross_eval")
CFG = {
    "corpus": BASE + "/data/corpus.jsonl",
    "queries": BASE + "/data/queries.jsonl",
    "out": "/tmp/li_probe_out.jsonl",
    "workers": 4,
    "k": 5,
}
GOLDEN = BASE + "/data/out_baseline.jsonl"

print("NAME =", repr(impl.NAME))
print("CAPS =", json.dumps(impl.CAPS, ensure_ascii=False))

for mode in ("normal", "sequential", "parallel", "retry", "resume"):
    t0 = time.perf_counter()
    try:
        r = impl.run(mode, CFG)
    except Exception as e:
        import traceback
        print("MODE %s RAISED %s: %s" % (mode, type(e).__name__, e))
        traceback.print_exc()
        continue
    dt = (time.perf_counter() - t0) * 1000.0
    sha = metrics.sha256_file(CFG["out"])
    print("---- MODE %s  wall=%.1f ms" % (mode, dt))
    print("   ok=%s" % r.get("ok"))
    for k in ("trace", "workers", "attempts", "error_text", "first_error",
              "steps_reexecuted_after_failure", "counts_before_failure",
              "counts_after_resume", "note"):
        if k in r:
            print("   %s = %s" % (k, json.dumps(r[k], ensure_ascii=False)))
    print("   n_results=%s" % (len(r.get("results") or [])))
    print("   sha256=%s  golden_match=%s" % (sha, sha == metrics.sha256_file(GOLDEN)))
print("PROBE_DONE")
