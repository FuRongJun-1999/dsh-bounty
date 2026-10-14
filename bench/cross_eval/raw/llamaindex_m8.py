# -*- coding: utf-8 -*-
"""M8：零凭据可运行性 + 运行期网络封锁证明。
   在 normal 模式整条流水线跑之前，把 socket 建连全部封死：
   若本实现真的发起网络请求，运行会直接失败。"""
import asyncio
import importlib.util
import os
import socket
import sys

import os as _os_path
_ROOT = _os_path.path.abspath(_os_path.path.join(
    _os_path.path.dirname(_os_path.path.abspath(__file__)), "..", "..", ".."))

ROOT = _os_path.path.join(_ROOT, "bench", "cross_eval")

print("### M8-3 环境内凭据类变量扫描（命中才打印，无输出=无凭据）")
pat = ("API_KEY", "OPENAI", "ANTHROPIC", "TOKEN", "SECRET", "CREDENTIAL", "PASSWORD")
hits = [(k, v) for k, v in os.environ.items() if any(p in k.upper() for p in pat)]
for k, v in hits:
    print("  CRED_ENV %s=%s" % (k, v[:6] + "..."))
print("  credential_like_env_count = %d" % len(hits))

print("### M8-4 运行期网络封锁：patch socket 建连后跑 normal 全流程")
NET_HITS = []


def _deny(*a, **kw):
    NET_HITS.append(a)
    raise RuntimeError("NETWORK_ACCESS_ATTEMPTED")


socket.socket.connect = _deny
socket.socket.connect_ex = _deny
socket.create_connection = _deny

spec = importlib.util.spec_from_file_location("impl_llamaindex_impl", ROOT + "/systems/llamaindex_impl.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

CFG = {"corpus": ROOT + "/data/corpus.jsonl", "queries": ROOT + "/data/queries.jsonl",
       "out": ROOT + "/raw/llamaindex_m8_out.jsonl", "workers": 4, "k": 5}
out = m.run("normal", CFG)
import hashlib
h = hashlib.sha256(open(CFG["out"], "rb").read()).hexdigest()
print("  normal ok=%s n_results=%d" % (out["ok"], len(out["results"])))
print("  sha256 = %s" % h)
print("  network_connect_attempts = %d" % len(NET_HITS))
print("  verdict = %s" % ("无网络访问，零凭据可跑通" if not NET_HITS else "发生过网络访问"))
print("M8_DONE")
