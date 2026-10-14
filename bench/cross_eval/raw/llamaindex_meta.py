# -*- coding: utf-8 -*-
"""M2/M3/M6/M8 与 resume 明细的原始证据收集（只读，不改任何被测文件）。"""
import importlib.util
import json
import os
import subprocess
import sys
import time

import os as _os_path
_ROOT = _os_path.path.abspath(_os_path.path.join(
    _os_path.path.dirname(_os_path.path.abspath(__file__)), "..", "..", ".."))

BASE = _os_path.path.join(_ROOT, "bench", "cross_eval")
H = BASE + "/harness"
S = BASE + "/systems"
IMPL = S + "/llamaindex_impl.py"
BASEIMPL = H + "/baseline.py"
sys.path.insert(0, H)
import metrics  # noqa: E402

import inspect  # noqa: E402
print("### M2 读数工具原文（metrics.loc）")
print(inspect.getsource(metrics.loc).rstrip())
print("### M2 代码规模（metrics.loc = 非空非注释行数）")
print("total_lines baseline.py = %d" % sum(1 for _ in open(BASEIMPL, encoding="utf-8")))
for p in (IMPL, BASEIMPL, H + "/workload.py"):
    print("loc %-24s = %d" % (os.path.basename(p), metrics.loc(p)))


def count_prefix(path, pat):
    n = 0
    for line in open(path, encoding="utf-8"):
        if line.strip().startswith(pat):
            n += 1
    return n


def count_sub(path, pat):
    return sum(1 for line in open(path, encoding="utf-8") if pat in line)


print("### M2 编排单元数")
print("@step 数（llamaindex_impl.py）      = %d" % count_prefix(IMPL, "@step"))
print("class 定义（llamaindex_impl.py）    = %d" % count_prefix(IMPL, "class "))
print("async def/def 步函数（llamaindex）  = %d" % (count_prefix(IMPL, "async def s_") + count_prefix(IMPL, "def s_")))
print("@step 数（baseline.py）             = %d" % count_prefix(BASEIMPL, "@step"))
print("### 反伪造核对：本实现里是否存在手写并发/重试/检查点循环")
for pat in ("ThreadPoolExecutor", "asyncio.to_thread", "Semaphore", "concurrent.futures",
            "while True", "for _attempt", "while attempt"):
    print("  %-22s 出现次数 = %d" % (pat, count_sub(IMPL, pat)))
print("  引擎 API 调用：retry_policy=%d  stop_after_attempt=%d  num_workers=%d  collect_events=%d  to_dict=%d  from_dict=%d"
      % (count_sub(IMPL, "retry_policy="), count_sub(IMPL, "stop_after_attempt("),
         count_sub(IMPL, "num_workers="), count_sub(IMPL, "collect_events("),
         count_sub(IMPL, "to_dict()"), count_sub(IMPL, "from_dict(")))

print()
print("### M3 冷启动 import 耗时（每次独立进程，/usr/bin/python3 -X utf8）")
COLD = (
    "import time,sys,importlib.util\n"
    "t0=time.perf_counter()\n"
    "spec=importlib.util.spec_from_file_location('impl_llamaindex_impl', " + repr(IMPL) + ")\n"
    "m=importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(m)\n"
    "print('%.1f' % ((time.perf_counter()-t0)*1000.0))\n"
)
env = dict(os.environ)
for i in range(5):
    r = subprocess.run(["/usr/bin/python3", "-X", "utf8", "-c", COLD],
                       capture_output=True, text=True, env=env)
    print("cold_import_run%d_ms = %s" % (i + 1, r.stdout.strip() or ("ERR " + r.stderr.strip()[-200:])))

ENGINE_ONLY = (
    "import time\n"
    "t0=time.perf_counter()\n"
    "import llama_index.core.workflow\n"
    "print('%.1f' % ((time.perf_counter()-t0)*1000.0))\n"
)
r = subprocess.run(["/usr/bin/python3", "-X", "utf8", "-c", ENGINE_ONLY],
                   capture_output=True, text=True, env=env)
print("engine_only_import_ms = %s" % r.stdout.strip())

print()
print("### M6 并发扇出 vs 串行（metrics.timeit，repeats=7 warmup=1）")
spec = importlib.util.spec_from_file_location("impl_llamaindex_impl", IMPL)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
CFG = {"corpus": BASE + "/data/corpus.jsonl", "queries": BASE + "/data/queries.jsonl",
       "out": BASE + "/raw/llamaindex_m6.jsonl", "workers": 4, "k": 5}
for mode in ("sequential", "parallel"):
    t = metrics.timeit(lambda m=mode: mod.run(m, dict(CFG)), repeats=7, warmup=1)
    print("M6 %-11s %s" % (mode, json.dumps(t, sort_keys=True)))
print("### M4/M5 明细（完整返回字典，results 略）")
for mode in ("resume", "retry"):
    r = mod.run(mode, dict(CFG))
    slim = {k: v for k, v in r.items() if k != "results"}
    slim["n_results"] = len(r.get("results") or [])
    print("DETAIL %s = %s" % (mode, json.dumps(slim, ensure_ascii=False, sort_keys=True)))

print()
print("### M8 依赖足迹")
for p in ("/home/ubuntu/dm/pylibs/base", "/home/ubuntu/dm/pylibs/llamaindex"):
    d = subprocess.run(["du", "-sh", p], capture_output=True, text=True)
    print("du -sh %s" % d.stdout.strip())
ls = subprocess.run(["ls", "-d", "/home/ubuntu/dm/pylibs/llamaindex/*.dist-info"],
                    capture_output=True, text=True)
for line in ls.stdout.strip().split("\n"):
    print("dist-info %s" % os.path.basename(line))
print("### M8 零凭据可运行性：环境里是否有 LLM 凭据")
for k in sorted(os.environ):
    if any(s in k.upper() for s in ("API_KEY", "OPENAI", "ANTHROPIC", "TOKEN", "SECRET")):
        print("  ENV_%s = <set>" % k)
print("  （上面若没有任何 ENV_ 行 = 环境内无凭据变量）")
print("  network_check: 本次全部读数由本地进程产生，未发起任何网络请求")
print("META_DONE")
