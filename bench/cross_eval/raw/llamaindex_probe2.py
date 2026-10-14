# -*- coding: utf-8 -*-
"""探针：验证 LlamaIndex Workflows 的 checkpoint/retry/fanout 语义。"""
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

class PStart(StartEvent):
    run_id: str = "r"

class E1(Event):
    tag: str = ""
class E2(Event):
    tag: str = ""
class E3(Event):
    tag: str = ""
class E4(Event):
    tag: str = ""
class E5(Event):
    tag: str = ""

class QEv(Event):
    idx: int = 0
class ROne(Event):
    idx: int = 0
    ids: list = []


def make_flow(fail_at_verify=0, workers=1):
    class Flow(Workflow):
        @step
        async def s_load(self, ev: PStart) -> E1:
            bump("load")
            return E1(tag="load")

        @step
        async def s_index(self, ev: E1) -> E2:
            bump("index")
            return E2(tag="index")

        @step
        async def s_dispatch(self, ctx: Context, ev: E2) -> E3:
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

        @step(retry_policy=retry_policy(
            retry=retry_if_exception_type(RuntimeError),
            wait=wait_none(),
            stop=stop_after_attempt(3)))
        async def s_verify(self, ctx: Context, ev: E4) -> E5:
            bump("verify")
            info = ctx.retry_info()
            print("   verify retry_number=%s" % info.retry_number)
            if info.retry_number < fail_at_verify:
                raise RuntimeError("injected transient failure")
            return E5(tag="verify")

        @step
        async def s_emit(self, ev: E5) -> StopEvent:
            bump("emit")
            return StopEvent(result={"ok": True, "counts": dict(COUNTS)})

    return Flow


async def t_normal():
    print("== T1 normal ==")
    COUNTS.clear()
    F = make_flow()
    wf = F(timeout=30)
    r = await wf.run(run_id="a")
    print("  result:", r)


async def t_retry():
    print("== T2 retry (2 injected failures) ==")
    COUNTS.clear()
    F = make_flow(fail_at_verify=2)
    wf = F(timeout=30)
    try:
        r = await wf.run(run_id="b")
        print("  result:", r)
    except Exception as e:
        print("  EXC", type(e).__name__, e)


async def t_fanout(workers):
    print("== T3 fanout workers=%d ==" % workers)
    COUNTS.clear()
    F = make_flow(workers=workers)
    wf = F(timeout=60)
    t0 = time.perf_counter()
    r = await wf.run(run_id="c")
    dt = (time.perf_counter() - t0) * 1000
    print("  wall_ms=%.1f counts=%s" % (dt, COUNTS))


async def t_checkpoint():
    print("== T4 checkpoint / resume ==")
    COUNTS.clear()
    SNAP = {}

    class CStart(StartEvent):
        run_id: str = "x"

    class A(Event):
        tag: str = ""
    class B(Event):
        tag: str = ""
    class C(Event):
        tag: str = ""
    class D(Event):
        tag: str = ""

    class CFlow(Workflow):
        @step
        async def s_a(self, ctx: Context, ev: CStart) -> A:
            bump("load")
            return A(tag="a")

        @step
        async def s_b(self, ctx: Context, ev: A) -> B:
            bump("index")
            return B(tag="b")

        @step
        async def s_c(self, ctx: Context, ev: B) -> C:
            bump("retrieve")
            # 在 retrieve 完成后立刻打快照（此刻队列里还没有 C 事件）
            SNAP["after_retrieve"] = ctx.to_dict()
            return C(tag="c")

        @step
        async def s_d(self, ctx: Context, ev: C) -> D:
            bump("verify")
            raise RuntimeError("injected failure at verify")

        @step
        async def s_e(self, ev: D) -> StopEvent:
            bump("emit")
            return StopEvent(result="done")

    wf = CFlow(timeout=30)
    try:
        await wf.run(run_id="x")
    except Exception as e:
        print("  run1 EXC %s: %s" % (type(e).__name__, e))
    print("  counts after run1:", dict(COUNTS))
    print("  snapshot keys:", sorted(SNAP["after_retrieve"].keys()))
    data = json.loads(json.dumps(SNAP["after_retrieve"], default=str))
    print("  snapshot json ok, len=%d" % len(json.dumps(data)))

    wf2 = CFlow(timeout=30)
    ctx2 = Context.from_dict(wf2, data)
    COUNTS.clear()
    try:
        r = await asyncio.wait_for(wf2.run(ctx=ctx2), timeout=20)
        print("  resume result:", r)
    except Exception as e:
        print("  resume EXC %s: %s" % (type(e).__name__, e))
    print("  counts after resume:", dict(COUNTS))


async def main():
    for t in (t_normal, t_retry, lambda: t_fanout(1), lambda: t_fanout(4), t_checkpoint):
        try:
            await t()
        except Exception as e:
            print("  PROBE EXC", type(e).__name__, e)
            traceback.print_exc()
        print()

asyncio.run(main())
