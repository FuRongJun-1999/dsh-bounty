# -*- coding: utf-8 -*-
"""探针 3：扇出语法修正 + checkpoint 语义 + 失败异常类型。"""
import asyncio, json, os, sys, time, traceback

import os as _os_path
_ROOT = _os_path.path.abspath(_os_path.path.join(
    _os_path.path.dirname(_os_path.path.abspath(__file__)), "..", "..", ".."))

HARNESS = _os_path.path.join(_ROOT, "bench", "cross_eval", "harness")
sys.path.insert(0, HARNESS)
import workload  # noqa

from llama_index.core.workflow import Workflow, step, Context, StartEvent, StopEvent, Event
from workflows.retry_policy import retry_policy, retry_if_exception_type, stop_after_attempt, wait_none

COUNTS = {}
def bump(k):
    COUNTS[k] = COUNTS.get(k, 0) + 1

class QEv(Event):
    idx: int = 0
class ROne(Event):
    idx: int = 0
    ids: list = []
class E3(Event):
    tag: str = ""
class E4(Event):
    tag: str = ""
class E5(Event):
    tag: str = ""


def make_flow(workers=1):
    class Flow(Workflow):
        @step
        async def s_dispatch(self, ctx: Context, ev: StartEvent) -> QEv | E3:
            bump("dispatch")
            for i in range(5):
                ctx.send_event(QEv(idx=i))
            return E3(tag="disp")

        @step(num_workers=workers)
        async def s_one(self, ev: QEv) -> ROne:
            bump("retrieve")
            await asyncio.sleep(0.05)
            return ROne(idx=ev.idx, ids=[ev.idx])

        @step
        async def s_gather(self, ctx: Context, ev: ROne | E3) -> E4 | None:
            evs = ctx.collect_events(ev, [E3] + [ROne] * 5)
            if evs is None:
                return None
            bump("gather")
            return E4(tag="gather")

        @step
        async def s_verify(self, ev: E4) -> E5:
            bump("verify")
            return E5(tag="verify")

        @step
        async def s_emit(self, ev: E5) -> StopEvent:
            bump("emit")
            return StopEvent(result={"ok": True})

    return Flow


async def t_fanout(workers):
    print("== fanout workers=%d ==" % workers)
    COUNTS.clear()
    wf = make_flow(workers)(timeout=60)
    t0 = time.perf_counter()
    r = await wf.run()
    dt = (time.perf_counter() - t0) * 1000
    print("  wall_ms=%.1f counts=%s result=%s" % (dt, dict(COUNTS), r))


async def t_retry():
    print("== retry ==")
    COUNTS.clear()
    class RFlow(Workflow):
        @step
        async def a(self, ev: StartEvent) -> StopEvent:
            return StopEvent(result=1)
    # separate: retry on a failing step
    class R2(Workflow):
        @step
        async def s1(self, ctx: Context, ev: StartEvent) -> StopEvent:
            bump("verify")
            info = ctx.retry_info()
            print("   retry_number=%s attempts_attr=%s" % (info.retry_number, getattr(info, "attempts", None)))
            if info.retry_number < 2:
                raise RuntimeError("injected transient failure")
            return StopEvent(result="done")
        s1._step_config.retry_policy = retry_policy(
            retry=retry_if_exception_type(RuntimeError), wait=wait_none(), stop=stop_after_attempt(3))
    wf = R2(timeout=30)
    try:
        r = await wf.run()
        print("  result=%s counts=%s" % (r, dict(COUNTS)))
    except Exception as e:
        print("  EXC %s: %s counts=%s" % (type(e).__name__, e, dict(COUNTS)))


async def t_checkpoint():
    print("== checkpoint / resume ==")
    COUNTS.clear()
    IN_VERIFY = asyncio.Event()
    SNAP_TAKEN = asyncio.Event()
    HOLD = {}

    class CFlow(Workflow):
        @step
        async def s_load(self, ev: StartEvent) -> E3:
            bump("load"); return E3(tag="load")
        @step
        async def s_index(self, ev: E3) -> E4:
            bump("index"); return E4(tag="index")
        @step
        async def s_retrieve(self, ev: E4) -> E5:
            bump("retrieve"); return E5(tag="retrieve")
        @step
        async def s_verify(self, ev: E5) -> E5:
            bump("verify")
            IN_VERIFY.set()
            await asyncio.wait_for(SNAP_TAKEN.wait(), timeout=10)
            raise RuntimeError("injected failure at verify")
        @step
        async def s_emit(self, ev: E5) -> StopEvent:
            bump("emit"); return StopEvent(result="done")

    wf = CFlow(timeout=30)
    handler = wf.run()
    await asyncio.wait_for(IN_VERIFY.wait(), timeout=10)
    snap = handler.ctx.to_dict()
    print("  snap keys:", sorted(snap.keys()))
    print("  snap json len:", len(json.dumps(snap, default=str)))
    HOLD["snap"] = snap
    SNAP_TAKEN.set()
    try:
        await handler
    except Exception as e:
        print("  run1 EXC %s: %s" % (type(e).__name__, e))
    print("  counts run1:", dict(COUNTS))

    data = json.loads(json.dumps(snap, default=str))
    wf2 = CFlow(timeout=30)
    ctx2 = Context.from_dict(wf2, data)
    COUNTS.clear()
    try:
        r = await asyncio.wait_for(wf2.run(ctx=ctx2), timeout=15)
        print("  resume result=%s" % (r,))
    except Exception as e:
        print("  resume EXC %s: %s" % (type(e).__name__, e))
    print("  counts resume:", dict(COUNTS))


async def main():
    for t in (lambda: t_fanout(1), lambda: t_fanout(4), t_retry, t_checkpoint):
        try:
            await t()
        except Exception as e:
            print("  PROBE EXC", type(e).__name__, e)
            traceback.print_exc()
        print()

asyncio.run(main())
