# -*- coding: utf-8 -*-
"""M7 证据：resume 注入失败时，引擎抛出的错误文本/回溯是否点名到具体 step。"""
import asyncio
import importlib.util
import traceback

import os as _os_path
_ROOT = _os_path.path.abspath(_os_path.path.join(
    _os_path.path.dirname(_os_path.path.abspath(__file__)), "..", "..", ".."))

IMPL = _os_path.path.join(_ROOT, "bench", "cross_eval", "systems", "llamaindex_impl.py")
BASE = _os_path.path.join(_ROOT, "bench", "cross_eval")
spec = importlib.util.spec_from_file_location("impl_llamaindex_impl", IMPL)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

CFG = {"corpus": BASE + "/data/corpus.jsonl", "queries": BASE + "/data/queries.jsonl",
       "out": BASE + "/raw/llamaindex_m7.jsonl", "workers": 4, "k": 5}


async def go():
    run_id = m._next_run_id("m7")
    m.EXEC.clear()
    m._new_art(CFG, run_id)
    hs = {"inject": "resume", "in_verify": asyncio.Event(), "snap_taken": asyncio.Event()}
    m.HS[run_id] = hs
    flow = m._build_flow(1)(timeout=600.0)
    handler = flow.run(start_event=m.PipeStart(run_id=run_id))
    await asyncio.wait_for(hs["in_verify"].wait(), timeout=120.0)
    snap = handler.ctx.to_dict()
    hs["snap"] = snap
    hs["snap_taken"].set()
    try:
        await asyncio.wait_for(handler, timeout=120.0)
        print("M7 NO_EXCEPTION (unexpected)")
    except Exception as e:
        print("M7 exc_type      = %s" % type(e).__name__)
        print("M7 exc_str       = %r" % str(e))
        print("M7 exc_module    = %s" % type(e).__module__)
        print("M7 'verify' in str(exc) = %s" % ("verify" in str(e)))
        print("M7 FULL_TRACEBACK_BEGIN")
        print(traceback.format_exc())
        print("M7 FULL_TRACEBACK_END")


asyncio.run(go())
print("M7_PROBE_DONE")
