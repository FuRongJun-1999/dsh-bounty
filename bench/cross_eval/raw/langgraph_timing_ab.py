"""交替 A/B 计时（spec 公平性规则要求「基线/方案轮换」）：
在同一进程内轮流跑 baseline 与 langgraph 的 sequential / parallel，避免单向漂移。
只读 harness/baseline.py，只写 raw/langgraph_timing_ab.txt。
"""
import importlib.util
import json
import os
import statistics
import sys
import time

import os as _os_path
_ROOT = _os_path.path.abspath(_os_path.path.join(
    _os_path.path.dirname(_os_path.path.abspath(__file__)), "..", "..", ".."))

ROOT = _ROOT
HARN = os.path.join(ROOT, "bench/cross_eval/harness")
sys.path.insert(0, HARN)
import workload  # noqa: E402


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


base = load(os.path.join(HARN, "baseline.py"), "impl_baseline")
lg = load(os.path.join(ROOT, "bench/cross_eval/systems/langgraph_impl.py"), "impl_langgraph")

DATA = os.path.join(ROOT, "bench/cross_eval/data")


def cfg(out):
    return {"corpus": os.path.join(DATA, "corpus.jsonl"),
            "queries": os.path.join(DATA, "queries.jsonl"),
            "out": out, "workers": 4, "k": workload.K_TOP}


CASES = [("baseline", base, "sequential"), ("langgraph", lg, "sequential"),
         ("baseline", base, "parallel"), ("langgraph", lg, "parallel")]

# 预热
for who, mod, mode in CASES:
    mod.run(mode, cfg("/tmp/ab_warm.jsonl"))

N = 9
res = {(w, m): [] for w, _, m in CASES}
for i in range(N):
    for who, mod, mode in CASES:
        t0 = time.perf_counter()
        mod.run(mode, cfg("/tmp/ab_%s_%s.jsonl" % (who, mode)))
        res[(who, mode)].append((time.perf_counter() - t0) * 1000.0)

lines = []
lines.append("AB_MODE=alternating rounds=%d workers=4 warmup=1" % N)
for who, mod, mode in CASES:
    xs = sorted(res[(who, mode)])
    r = {"n": len(xs), "min_ms": round(xs[0], 3),
         "p50_ms": round(statistics.median(xs), 3),
         "p95_ms": round(xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))], 3),
         "all_ms": [round(x, 3) for x in xs]}
    lines.append("AB %s %-10s %s" % (who, mode, json.dumps(r, sort_keys=True)))

bs = statistics.median(res[("baseline", "sequential")])
bp = statistics.median(res[("baseline", "parallel")])
ls = statistics.median(res[("langgraph", "sequential")])
lp = statistics.median(res[("langgraph", "parallel")])
lines.append("AB_RATIO baseline parallel/sequential p50 = %.3f" % (bp / bs))
lines.append("AB_RATIO langgraph parallel/sequential p50 = %.3f" % (lp / ls))
lines.append("AB_RATIO langgraph/baseline sequential p50 = %.3f" % (ls / bs))
lines.append("AB_RATIO langgraph/baseline parallel   p50 = %.3f" % (lp / bp))

# ---- 扇出并发度本身的读数：同一张 Send 图，只改 max_concurrency ----
app_fan = lg._build(fanout=True)


def fan_once(w, n=5):
    xs = []
    for _ in range(n):
        ctx = {"corpus": os.path.join(DATA, "corpus.jsonl"),
               "queries": os.path.join(DATA, "queries.jsonl"),
               "out": "/tmp/ab_fan.jsonl", "k": workload.K_TOP, "counts": {}}
        t0 = time.perf_counter()
        app_fan.invoke({}, {"configurable": {"ctx": ctx}, "max_concurrency": w})
        xs.append((time.perf_counter() - t0) * 1000.0)
    xs.sort()
    return {"n": n, "min_ms": round(xs[0], 3), "p50_ms": round(statistics.median(xs), 3)}


f1, f4, f40 = fan_once(1), fan_once(4), fan_once(40)
lines.append("AB_FANOUT max_concurrency=1  %s" % json.dumps(f1, sort_keys=True))
lines.append("AB_FANOUT max_concurrency=4  %s" % json.dumps(f4, sort_keys=True))
lines.append("AB_FANOUT max_concurrency=40 %s" % json.dumps(f40, sort_keys=True))
lines.append("AB_FANOUT p50 ratio conc=4 / conc=1 = %.3f" % (f4["p50_ms"] / f1["p50_ms"]))

out = os.path.join(ROOT, "bench/cross_eval/raw/langgraph_timing_ab.txt")
with open(out, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(lines) + "\n")
print("\n".join(lines))
print("AB_WRITTEN raw/langgraph_timing_ab.txt")
