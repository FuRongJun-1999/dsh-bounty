# -*- coding: utf-8 -*-
"""M3 冷启动 import 耗时：基线 vs 本方案，交替各 5 次独立进程（公平性规则：计时交替进行）。"""
import json
import os
import subprocess
import time

PY = "/usr/bin/python3"
import os as _os_path
_ROOT = _os_path.path.abspath(_os_path.path.join(
    _os_path.path.dirname(_os_path.path.abspath(__file__)), "..", "..", ".."))

ROOT = _os_path.path.join(_ROOT, "bench", "cross_eval")
HARNESS = ROOT + "/harness"
ENV = dict(os.environ)
ENV["PYTHONPATH"] = "/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/llamaindex"

SNIP = (
    "import importlib.util as iu, sys;"
    "sys.path.insert(0, %r);"
    "spec = iu.spec_from_file_location('impl_x', %r);"
    "m = iu.module_from_spec(spec);"
    "spec.loader.exec_module(m);"
    "print('OK', m.NAME)"
)

CASES = [
    ("baseline", HARNESS + "/baseline.py"),
    ("llamaindex", ROOT + "/systems/llamaindex_impl.py"),
]

res = {"baseline": [], "llamaindex": []}
for i in range(5):
    for name, path in CASES:
        code = SNIP % (HARNESS, path)
        t0 = time.perf_counter()
        p = subprocess.run([PY, "-X", "utf8", "-c", code], env=ENV,
                           capture_output=True, text=True)
        dt = (time.perf_counter() - t0) * 1000.0
        ok = (p.returncode == 0 and "OK" in p.stdout)
        res[name].append(round(dt, 1))
        print("cold_import %-10s run%d = %.1f ms  rc=%d ok=%s" % (name, i + 1, dt, p.returncode, ok))
        if not ok:
            print("  STDERR: %s" % p.stderr.strip()[-500:])

for name in ("baseline", "llamaindex"):
    v = res[name]
    print("cold_import_%s_ms = %s" % (name, json.dumps(v)))
    print("cold_import_%s_min_ms = %.1f" % (name, min(v)))
print("COLDIMPORT_DONE")
