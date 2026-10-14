# -*- coding: utf-8 -*-
"""LlamaIndex Workflows（事件驱动工作流）实现：与手写基线同一个确定性五步流水线。

引擎：llama-index-core 0.14.25 + llama-index-workflows 2.26.0。
编排能力全部来自引擎本身，没有手写并发池 / 重试循环 / 检查点循环：

- 扇出      ：@step 返回 list[Event] —— 引擎原生 fan-out
              （workflows/utils.py:455 _is_fan_out_return，
               workflows/runtime/types/step_function.py:305
               "A step that actually returned a list fans out"）；
              并发上限 @step(num_workers=N)
              （workflows/decorators.py:126；
               workflows/runtime/types/internal_state.py:844
               "num_workers: Maximum number of concurrent executions of this step"）。
- 并发执行  ：检索步写成同步函数，引擎自动把它放进默认线程池
              （workflows/runtime/types/step_function.py:284-293
               "coerce to coroutine function ... run_in_executor(None, ...)"）。
- 重试      ：@step(retry_policy=retry_policy(...))
              （workflows/decorators.py:127；workflows/retry_policy.py:853）。
- 检查点/恢复：Context.to_dict() / Context.from_dict()
              （workflows/context/context.py:357 / :398）
              + Workflow.run(ctx=restored)（workflows/workflow.py:354）。
              引擎限定 to_dict() 只能从 handler 代码调用，步内调用会抛
              ContextStateError（实测原文见 raw/llamaindex_probe3.txt）。

五步一律调用 harness/workload.py 的纯函数，与基线/其它引擎共用同一检索器。

读数口径（与 harness/spec.md「读数项」一致）：本模块的 `trace` 由**真实执行序列**
`SEQ` 推导（`_bump` 每次真实进入一个 step 就追加一条，含重复），**不是**字面量自述。
"""
import asyncio
import json
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_HARNESS = os.path.normpath(os.path.join(_HERE, os.pardir, "harness"))
if _HARNESS not in sys.path:
    sys.path.insert(0, _HARNESS)

import workload  # noqa: E402

# 主 API 走 LlamaIndex 命名空间（llama_index.core.workflow 是 workflows 包的薄转发层）
from llama_index.core.workflow import (  # noqa: E402
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)

# 组合式重试策略只从 workflows.retry_policy 导出（同一 wheel；
# llama_index.core.workflow.retry_policy 只转发 RetryPolicy / 已废弃的 ConstantDelayRetryPolicy）
from workflows.retry_policy import (  # noqa: E402
    retry_if_exception_type,
    retry_policy,
    stop_after_attempt,
    wait_none,
)

NAME = "llamaindex"

CAPS = {
    "checkpoint": True,
    "retry": True,
    "fanout": True,
    "note": (
        "checkpoint=Context.to_dict()/from_dict()（引擎限定只能从 handler 代码取，"
        "同进程内恢复；跨进程需自行持久化索引与 payload）；"
        "retry=@step(retry_policy=retry_policy(...))，作用域是单个 step 的单次执行；"
        "fanout=@step 返回 list[Event] + @step(num_workers=N)，"
        "同步步体由引擎自动 run_in_executor 放默认线程池"
    ),
}

# verify 步挂载的重试策略：只重试 RuntimeError，立即重试，最多 3 次尝试
_VERIFY_RETRY_POLICY = retry_policy(
    retry=retry_if_exception_type(RuntimeError),
    wait=wait_none(),
    stop=stop_after_attempt(3),
)

# ---- 模块级执行计数表：每个 step 入口自增，用来产出真实执行轨迹 ----
EXEC = {}
# ---- 模块级真实执行序列（resume 档两遍合并）：trace 由它推导，不用字面量自述 ----
SEQ = []


def _bump(name):
    EXEC[name] = EXEC.get(name, 0) + 1
    SEQ.append(name)


# ---- 进程内产物登记处：BM25Okapi 对象不可 JSON 序列化，按 run_id 存进程内 ----
ART = {}

# ---- resume 用的 handler 侧握手槽位（key = run_id）----
HS = {}

_STEP_ORDER = ("load", "index", "retrieve", "verify", "emit")

_seq = [0]


def _next_run_id(mode):
    _seq[0] += 1
    return "li-%s-%d" % (mode, _seq[0])


# ---------------------------------------------------------------- 事件定义
class PipeStart(StartEvent):
    run_id: str = ""


class LoadedEv(Event):
    run_id: str = ""


class IndexedEv(Event):
    run_id: str = ""


class QueryEv(Event):
    run_id: str = ""
    idx: int = 0


class RetrievedEv(Event):
    run_id: str = ""
    idx: int = 0
    rec_json: str = ""


class RetrievedAllEv(Event):
    run_id: str = ""
    recs_json: str = ""


class VerifiedEv(Event):
    run_id: str = ""
    recs_json: str = ""


# ---------------------------------------------------------------- 工作流工厂
_FLOWS = {}


def _build_flow(workers):
    """按 num_workers 构建（并缓存）工作流类；num_workers 是装饰器参数，只能在建类时定。"""
    if workers in _FLOWS:
        return _FLOWS[workers]

    class PipelineFlow(Workflow):
        # 步骤 1/5 load：读语料（workload 纯函数）
        @step
        async def s_load(self, ev: PipeStart) -> LoadedEv:
            _bump("load")
            ART[ev.run_id]["docs"] = workload.step_load(ART[ev.run_id]["corpus"])
            return LoadedEv(run_id=ev.run_id)

        # 步骤 2/5 index：建 BM25（workload 纯函数）
        @step
        async def s_index(self, ev: LoadedEv) -> IndexedEv:
            _bump("index")
            ART[ev.run_id]["index"] = workload.step_index(ART[ev.run_id]["docs"])
            return IndexedEv(run_id=ev.run_id)

        # 步骤 3/5 retrieve（扇出端）：读查询，返回 list[Event] 触发引擎原生 fan-out
        @step
        async def s_fanout(self, ev: IndexedEv) -> list[QueryEv]:
            _bump("fanout")
            art = ART[ev.run_id]
            art["queries"] = workload.load_queries(art["queries_path"])
            return [QueryEv(run_id=ev.run_id, idx=i) for i in range(len(art["queries"]))]

        # 步骤 3/5 retrieve（单条）：同步函数 ⇒ 引擎 run_in_executor 放线程池，
        # num_workers 决定同一 step 的最大并发执行数
        @step(num_workers=workers)
        def s_retrieve_one(self, ev: QueryEv) -> RetrievedEv:
            _bump("retrieve")
            art = ART[ev.run_id]
            rec = workload.step_retrieve(art["index"], [art["queries"][ev.idx]], art["k"])[0]
            return RetrievedEv(run_id=ev.run_id, idx=ev.idx,
                               rec_json=json.dumps(rec, ensure_ascii=False, sort_keys=True))

        # 步骤 3/5 retrieve（归并端）：用引擎的 ctx.collect_events 等齐 N 条，按 idx 还原查询顺序
        @step
        async def s_gather(self, ctx: Context, ev: RetrievedEv) -> RetrievedAllEv | None:
            art = ART[ev.run_id]
            evs = ctx.collect_events(ev, [RetrievedEv] * len(art["queries"]))
            if evs is None:
                return None
            _bump("gather")
            recs = [json.loads(e.rec_json) for e in sorted(evs, key=lambda e: e.idx)]
            return RetrievedAllEv(run_id=ev.run_id,
                                  recs_json=json.dumps(recs, ensure_ascii=False, sort_keys=True))

        # 步骤 4/5 verify：挂引擎重试策略；注入逻辑只改抛不抛异常，不改正常路径
        @step(retry_policy=_VERIFY_RETRY_POLICY)
        async def s_verify(self, ctx: Context, ev: RetrievedAllEv) -> VerifiedEv:
            _bump("verify")
            hs = HS.get(ev.run_id) or {}
            if hs.get("inject") == "resume":
                # resume：先把 handler 侧叫起来取检查点，再抛注入异常
                hs["in_verify"].set()
                await asyncio.wait_for(hs["snap_taken"].wait(), timeout=60.0)
                raise RuntimeError("injected failure at verify")
            if hs.get("inject") == "retry":
                # 引擎自己的重试账本：retry_number 首次为 0，第一次重试为 1
                n = ctx.retry_info().retry_number
                hs["attempts"] = n + 1
                if n < 2:
                    raise RuntimeError("injected transient failure")
            art = ART[ev.run_id]
            verified = workload.step_verify(art["index"], json.loads(ev.recs_json))
            return VerifiedEv(run_id=ev.run_id,
                              recs_json=json.dumps(verified, ensure_ascii=False, sort_keys=True))

        # 步骤 5/5 emit：写结果 JSONL（workload 纯函数）
        @step
        async def s_emit(self, ev: VerifiedEv) -> StopEvent:
            _bump("emit")
            art = ART[ev.run_id]
            verified = json.loads(ev.recs_json)
            workload.step_emit(verified, art["out"])
            return StopEvent(result={"results": verified, "out": art["out"]})

    # 序列化器用 value.__module__ + "." + value.__class__.__name__ 反查类
    # （workflows/context/utils.py:12 get_qualified_name），所以给每个 workers
    # 变体一个唯一类名并挂到模块全局，保证 getattr(module, 类名) 能取到。
    _cls_name = "PipelineFlowW%d" % workers
    PipelineFlow.__name__ = _cls_name
    PipelineFlow.__qualname__ = _cls_name
    globals()[_cls_name] = PipelineFlow
    _reg = sys.modules.get(__name__)
    if _reg is not None and _reg.__dict__ is not globals():
        setattr(_reg, _cls_name, PipelineFlow)
    _FLOWS[workers] = PipelineFlow
    return PipelineFlow


def _new_art(cfg, run_id):
    ART[run_id] = {
        "corpus": cfg["corpus"],
        "queries_path": cfg["queries"],
        "out": cfg["out"],
        "k": cfg.get("k", workload.K_TOP),
    }


def _trace():
    return [s for s in _STEP_ORDER if EXEC.get(s)]


# ---------------------------------------------------------------- 各模式
async def _run_plain(cfg, run_id, workers):
    HS[run_id] = {"inject": None}
    flow = _build_flow(workers)(timeout=600.0)
    stop = await flow.run(start_event=PipeStart(run_id=run_id))
    return {"ok": True, "trace": _trace(), "workers": workers,
            "results": stop["results"], "out": cfg["out"]}


async def _run_retry(cfg, run_id, workers):
    hs = {"inject": "retry", "attempts": 0}
    HS[run_id] = hs
    flow = _build_flow(workers)(timeout=600.0)
    stop = await flow.run(start_event=PipeStart(run_id=run_id))
    return {"ok": True, "attempts": hs["attempts"],
            "error_text": "injected transient failure",
            "results": stop["results"], "out": cfg["out"]}


async def _run_resume(cfg, run_id, workers):
    hs = {"inject": "resume", "in_verify": asyncio.Event(), "snap_taken": asyncio.Event()}
    HS[run_id] = hs
    flow = _build_flow(workers)(timeout=600.0)
    handler = flow.run(start_event=PipeStart(run_id=run_id))
    # 引擎限定：检查点只能在 handler 代码里取（步内调用抛 ContextStateError）
    await asyncio.wait_for(hs["in_verify"].wait(), timeout=120.0)
    snap = handler.ctx.to_dict()
    hs["snap"] = snap
    hs["snap_taken"].set()

    first_error = None
    try:
        await asyncio.wait_for(handler, timeout=120.0)
    except Exception as e:  # 引擎把步内异常包成 WorkflowRuntimeError，原文一并记下
        first_error = "%s: %s" % (type(e).__name__, e)
    failed_after = dict(EXEC)

    # 恢复：Context.from_dict() 重建上下文，Workflow.run(ctx=...) 续跑
    data = json.loads(json.dumps(snap, default=str))
    EXEC.clear()
    HS[run_id] = {"inject": None}
    flow2 = _build_flow(workers)(timeout=600.0)
    ctx2 = Context.from_dict(flow2, data)
    stop = await asyncio.wait_for(flow2.run(ctx=ctx2), timeout=120.0)
    reexec = _trace()
    return {"ok": True, "first_error": first_error,
            "steps_reexecuted_after_failure": reexec,
            # trace = 真实执行序列（SEQ 由 _bump 逐次追加，两遍合并，含重复），
            # 不再是 ["load","index","retrieve","verify","emit"] 这样的字面量自述。
            "trace": list(SEQ),
            "counts_before_failure": {k: failed_after.get(k, 0) for k in _STEP_ORDER},
            "counts_after_resume": {k: EXEC.get(k, 0) for k in _STEP_ORDER},
            "results": stop["results"], "out": cfg["out"]}


def run(mode, cfg):
    """runner.py 以同步方式调用；内部用 asyncio.run 驱动事件驱动工作流。"""
    if mode not in ("normal", "sequential", "parallel", "resume", "retry"):
        raise ValueError("unsupported mode: %s" % mode)
    workers = int(cfg.get("workers", 4) or 4) if mode == "parallel" else 1
    run_id = _next_run_id(mode)
    EXEC.clear()
    SEQ.clear()
    _new_art(cfg, run_id)
    try:
        if mode == "resume":
            return asyncio.run(_run_resume(cfg, run_id, workers))
        if mode == "retry":
            return asyncio.run(_run_retry(cfg, run_id, workers))
        return asyncio.run(_run_plain(cfg, run_id, workers))
    finally:
        ART.pop(run_id, None)
        HS.pop(run_id, None)


# ---------------------------------------------------------------- 自身登记
# runner.py 用 spec_from_file_location() + exec_module() 加载本模块，**不注册 sys.modules**；
# 而 Context.to_dict() 会把事件类写成「模块名.类名」
# （workflows/context/serializers.py:215 -> utils.py:12 get_qualified_name），
# Context.from_dict() 再按该名字 import_module()
# （serializers.py:192 resolve_class -> workflows/context/utils.py:53
# import_module_from_qualified_name）。不登记就会在 resume 恢复时抛
# ModuleNotFoundError: No module named 'impl_llamaindex_impl'
# （原始报错见 raw/llamaindex_probe_module_registration.txt）。
# 必须在所有事件类定义之后执行，因为这里用的是快照式登记。
if __name__ not in sys.modules:
    _self_module = types.ModuleType(__name__)
    _self_module.__dict__.update(globals())
    sys.modules[__name__] = _self_module
