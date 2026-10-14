"""LangGraph（LangChain 官方图状态机）实现：同一个确定性五步流水线。

被测引擎：langgraph 1.2.15（依赖 langgraph-checkpoint 4.3.0 / langchain-core 1.6.10）
评测契约：bench/cross_eval/harness/spec.md
五步（load / index / retrieve / verify / emit）的**计算逻辑全部调用 harness/workload.py 的纯函数**
（检索算法四家共用，保证对照公平）；本文件只负责「编排」——顺序、扇出、重试、检查点恢复——
且编排能力全部来自 LangGraph 自身 API，不用自写循环冒充引擎能力。

本文件用到的 LangGraph API（逐处见节点内的中文注释）：
  1. langgraph.graph.StateGraph / START / END                   图状态机骨架
  2. StateGraph.add_node / add_edge                             节点与顺序边
  3. StateGraph.add_conditional_edges + langgraph.types.Send    动态扇出（一查询一任务）
  4. config["max_concurrency"]                                  扇出并发度
  5. langgraph.types.RetryPolicy                                节点级内建重试
  6. langgraph.checkpoint.memory.InMemorySaver                  线程级检查点（断点续跑）
  7. JsonPlusSerializer(pickle_fallback=True)                   检查点序列化（默认 serde 存不下 BM25Okapi）

运行方式见同目录 raw/langgraph_run.sh 与 docs/reviews/LangGraph_v0.1.md §2。
"""
import json
import operator
import os
import sys
import time
import traceback
from typing import Annotated, TypedDict

# harness 目录（workload.py 所在）：runner.py 也会插，但独立 import 时要自己插
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "harness"))
import workload  # noqa: E402

from langgraph.graph import StateGraph, START, END  # noqa: E402
from langgraph.types import Send, RetryPolicy  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer  # noqa: E402

NAME = "langgraph"

# checkpoint/retry/fanout 三项均为引擎内建，依据：
#   checkpoint -> langgraph/checkpoint/memory/__init__.py 的 InMemorySaver（线程级检查点）
#   retry      -> langgraph/types.py 的 RetryPolicy（节点级重试）
#   fanout     -> langgraph/types.py 的 Send + config["max_concurrency"]（动态扇出）
# 注意：默认 serde 的 pickle_fallback=False（langgraph/checkpoint/serde/jsonplus.py:122），
# 而状态里带 BM25Okapi（rank_bm25），故检查点必须显式开 pickle_fallback=True，否则
# put_writes 抛 "TypeError: Type is not msgpack serializable: BM25Okapi"。
# 另：RetryPolicy 默认 retry_on=default_retry_on，而该函数对 RuntimeError 返回 False
# （langgraph/_internal/_retry.py），故必须显式 retry_on=RuntimeError 才会重试。
CAPS = {
    "checkpoint": True,
    "retry": True,
    "fanout": True,
    "note": ("checkpoint=InMemorySaver(serde=JsonPlusSerializer(pickle_fallback=True))"
             "（langgraph/checkpoint/memory/__init__.py；默认 pickle_fallback=False 见 "
             "langgraph/checkpoint/serde/jsonplus.py:122，默认 serde 无法序列化 BM25Okapi）；"
             "retry=RetryPolicy(retry_on=RuntimeError)（langgraph/types.py；默认 default_retry_on 对 "
             "RuntimeError 返回 False，见 langgraph/_internal/_retry.py）；"
             "fanout=Send+config[max_concurrency]（langgraph/types.py）"),
}

# 五步的规范顺序（用于从真实执行计数里推导「哪些步骤被重跑」）
ORDER = ["load", "index", "retrieve", "verify", "emit"]

# 每个 mode 只往 stdout 打一次证据行（runner 的计时循环会重复调用 run，避免刷屏）
_PRINTED = set()


def _evidence(mode, msg):
    """把机器可读的证据打到 stdout —— 会被 runner 的 tee 落进 raw/langgraph_runner.txt。"""
    if mode in _PRINTED:
        return
    _PRINTED.add(mode)
    print("LANGGRAPH_EVIDENCE mode=%s %s" % (mode, msg), flush=True)


# --------------------------------------------------------------------------
# 状态（StateGraph 的 channel 定义）
# --------------------------------------------------------------------------
def _merge_by_i(left, right):
    """扇出结果的归约器：按查询序号 i 排序合并，保证并发完成顺序不影响产物（确定性）。"""
    return sorted((left or []) + (right or []), key=lambda x: x["i"])


class PipelineState(TypedDict, total=False):
    docs: list
    index: dict
    queries: list
    # 线性图里由单个 retrieve 节点一次写入；扇出图里由 40 个 retrieve_one 任务并发写入，
    # 因此该 channel 必须带归约器（LangGraph 的 Annotated[..., reducer] 语义）。
    retrieved: Annotated[list, _merge_by_i]
    verified: list
    # 真实执行轨迹：每个节点被调用时追加一次自己的名字（operator.add = list 拼接归约器）
    trace: Annotated[list, operator.add]


def _ctx(config):
    """从 LangGraph 的 RunnableConfig 里取本次运行的上下文（语料路径 / 输出路径 / 执行计数）。"""
    return ((config or {}).get("configurable") or {}).get("ctx") or {}


def _bump(config, node):
    """节点被真实调用的计数 —— resume/retry 的重跑名单与尝试次数都由它推导，不硬编码。"""
    c = _ctx(config)
    counts = c.setdefault("counts", {})
    counts[node] = counts.get(node, 0) + 1


# --------------------------------------------------------------------------
# 五个步骤对应的图节点（计算全部委托 workload 纯函数）
# --------------------------------------------------------------------------
def _n_load(state, config):
    """第 1 步 load：StateGraph 节点。"""
    _bump(config, "load")
    return {"docs": workload.step_load(_ctx(config)["corpus"]), "trace": ["load"]}


def _n_index(state, config):
    """第 2 步 index：StateGraph 节点，产物写进 state["index"] channel。"""
    _bump(config, "index")
    return {"index": workload.step_index(state["docs"]), "trace": ["index"]}


def _n_retrieve(state, config):
    """第 3 步 retrieve（串行版）：一个节点内逐条查询检索，与基线 sequential 同语义。"""
    _bump(config, "retrieve")
    c = _ctx(config)
    queries = workload.load_queries(c["queries"])
    out = []
    for i, q in enumerate(queries):
        r = dict(workload.step_retrieve(state["index"], [q], c["k"])[0])
        r["i"] = i  # 归约用的序号（只进 state，不进最终产物）
        out.append(r)
    return {"queries": queries, "retrieved": out, "trace": ["retrieve"]}


def _n_retrieve_fan(state, config):
    """第 3 步 retrieve（扇出版）：只负责装载查询，真正的检索交给 Send 扇出的 retrieve_one。"""
    _bump(config, "retrieve")
    return {"queries": workload.load_queries(_ctx(config)["queries"]), "trace": ["retrieve"]}


def _fan_out(state):
    """LangGraph 动态扇出 API：add_conditional_edges 的路由函数返回一组 Send。

    每个 Send(node, payload) 生成一个**独立任务**，payload 是该任务的输入
    （LangGraph 只把 payload 传给目标节点，不与图状态合并，故这里带上 index 引用）。
    并发度由运行时 config["max_concurrency"] 控制。
    """
    return [Send("retrieve_one", {"q": q, "i": i, "index": state["index"]})
            for i, q in enumerate(state["queries"])]


def _n_retrieve_one(state, config):
    """扇出的单个检索任务：输入是 Send 的 payload，输出经 _merge_by_i 归约回 retrieved channel。"""
    _bump(config, "retrieve_one")
    r = dict(workload.step_retrieve(state["index"], [state["q"]], _ctx(config)["k"])[0])
    r["i"] = state["i"]
    return {"retrieved": [r]}


def _n_verify(state, config):
    """第 4 步 verify：只保留正文含全部查询词的命中。"""
    _bump(config, "verify")
    return {"verified": workload.step_verify(state["index"], state["retrieved"]), "trace": ["verify"]}


def _n_emit(state, config):
    """第 5 步 emit：写结果 JSONL。"""
    _bump(config, "emit")
    workload.step_emit(state["verified"], _ctx(config)["out"])
    return {"trace": ["emit"]}


def _n_verify_failonce(state, config):
    """resume 专用 verify：第一次调用抛 RuntimeError（模拟第 4 步前失败），之后正常。"""
    _bump(config, "verify")
    if _ctx(config)["counts"]["verify"] == 1:
        raise RuntimeError("injected failure at verify")
    return {"verified": workload.step_verify(state["index"], state["retrieved"]), "trace": ["verify"]}


def _n_verify_transient(state, config):
    """retry 专用 verify：前两次调用抛 RuntimeError（瞬时故障），第 3 次成功。

    重试本身由 LangGraph 的 RetryPolicy 驱动（不是本函数里的循环）。
    """
    _bump(config, "verify")
    if _ctx(config)["counts"]["verify"] < 3:
        raise RuntimeError("injected transient failure")
    return {"verified": workload.step_verify(state["index"], state["retrieved"]), "trace": ["verify"]}


# --------------------------------------------------------------------------
# 图构建（StateGraph API）
# --------------------------------------------------------------------------
def _build(verify_fn=None, fanout=False, checkpointer=None, retry_policy=None):
    """用 StateGraph 组装五步图。

    - 线性图：START -> load -> index -> retrieve -> verify -> emit -> END
    - 扇出图：START -> load -> index -> retrieve -(Send x N)-> retrieve_one -> verify -> emit -> END
    """
    g = StateGraph(PipelineState)
    g.add_node("load", _n_load)
    g.add_node("index", _n_index)
    if fanout:
        g.add_node("retrieve", _n_retrieve_fan)
        g.add_node("retrieve_one", _n_retrieve_one)
    else:
        g.add_node("retrieve", _n_retrieve)
    if retry_policy is not None:
        # LangGraph 节点级内建重试：把 RetryPolicy 挂在节点上，重试由 pregel 执行器负责
        g.add_node("verify", verify_fn or _n_verify, retry_policy=retry_policy)
    else:
        g.add_node("verify", verify_fn or _n_verify)
    g.add_node("emit", _n_emit)

    g.add_edge(START, "load")
    g.add_edge("load", "index")
    g.add_edge("index", "retrieve")
    if fanout:
        # 动态扇出：路由函数返回 [Send, Send, ...]
        g.add_conditional_edges("retrieve", _fan_out, ["retrieve_one"])
        g.add_edge("retrieve_one", "verify")
    else:
        g.add_edge("retrieve", "verify")
    g.add_edge("verify", "emit")
    g.add_edge("emit", END)

    # checkpointer：挂上后每个 superstep 落检查点，可用同一 thread_id 断点续跑
    return g.compile(checkpointer=checkpointer)


# 编译一次、多次 invoke（LangGraph 的常规用法）。一次性构图开销单独在 __main__ 里量。
_APPS = {}


def _app(kind):
    if kind not in _APPS:
        _APPS[kind] = _build(fanout=(kind == "fanout"))
    return _APPS[kind]


def _new_ctx(cfg):
    return {"corpus": cfg["corpus"], "queries": cfg["queries"], "out": cfg["out"],
            "k": cfg.get("k", workload.K_TOP), "counts": {}}


# --------------------------------------------------------------------------
# 五个模式
# --------------------------------------------------------------------------
def run(mode, cfg):
    """mode ∈ normal / resume / retry / sequential / parallel。"""
    out = cfg["out"]

    if mode in ("normal", "sequential"):
        ctx = _new_ctx(cfg)
        st = _app("linear").invoke({}, {"configurable": {"ctx": ctx}})
        return {"ok": True, "trace": st["trace"], "workers": 1,
                "results": st["verified"], "out": out}

    if mode == "parallel":
        # 该引擎自己的扇出能力：Send + config["max_concurrency"]（并发 worker = cfg["workers"]）
        workers = cfg.get("workers", 4)
        ctx = _new_ctx(cfg)
        st = _app("fanout").invoke({}, {"configurable": {"ctx": ctx}, "max_concurrency": workers})
        _evidence("parallel", "engine=Send+max_concurrency workers=%d node_exec_counts=%s trace=%s"
                  % (workers, json.dumps(ctx["counts"], sort_keys=True), json.dumps(st["trace"])))
        return {"ok": True, "trace": st["trace"], "workers": workers,
                "results": st["verified"], "out": out}

    if mode == "resume":
        # 检查点：InMemorySaver 每个 superstep 落盘；verify 第一次抛错后，
        # 用同一个 thread_id 再 invoke(None)，LangGraph 从最后一个检查点继续。
        ctx = _new_ctx(cfg)
        serde = JsonPlusSerializer(pickle_fallback=True)  # 状态含 BM25Okapi，默认 serde 存不下
        app = _build(verify_fn=_n_verify_failonce, checkpointer=InMemorySaver(serde=serde))
        rc = {"configurable": {"ctx": ctx, "thread_id": "langgraph-resume-thread"}}
        first_error, tb, state_next = None, "", None
        try:
            app.invoke({}, rc)
        except RuntimeError as e:
            first_error = str(e)
            tb = traceback.format_exc()
            # 失败后检查点的 next：LangGraph 记下了「下一步该跑谁」
            state_next = list(app.get_state(rc).next)
        # 断点续跑：输入 None = 不喂新输入，从检查点继续
        st = app.invoke(None, rc)
        counts = ctx["counts"]
        reexec = [n for n in ORDER if counts.get(n, 0) > 1]           # 真实执行计数 >1 = 被重跑
        reused = [n for n in ORDER[:3] if counts.get(n, 0) == 1]      # 检查点里复用的前序步骤
        named = [ln.strip() for ln in tb.splitlines() if "During task with name" in ln]
        _evidence("resume", "engine=InMemorySaver first_error=%s checkpoint_next_after_failure=%s "
                            "node_exec_counts=%s steps_reexecuted_after_failure=%s "
                            "steps_reused_from_checkpoint=%s error_names_node=%s error_node_line=%s"
                  % (json.dumps(first_error), json.dumps(state_next),
                     json.dumps(counts, sort_keys=True), json.dumps(reexec), json.dumps(reused),
                     json.dumps(bool(named)), json.dumps(named[-1] if named else "")))
        return {"ok": True, "first_error": first_error,
                "steps_reexecuted_after_failure": reexec,
                "results": st["verified"], "out": out}

    if mode == "retry":
        # 重试：LangGraph 内建 RetryPolicy（必须显式 retry_on=RuntimeError，
        # 因为默认 default_retry_on 对 RuntimeError 返回 False）。
        ctx = _new_ctx(cfg)
        policy = RetryPolicy(max_attempts=3, retry_on=RuntimeError)
        app = _build(verify_fn=_n_verify_transient, retry_policy=policy)
        t0 = time.perf_counter()
        st = app.invoke({}, {"configurable": {"ctx": ctx}})
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        attempts = ctx["counts"]["verify"]  # 真实节点调用次数，不是硬编码
        _evidence("retry", "engine=RetryPolicy(max_attempts=3,retry_on=RuntimeError) "
                           "attempts=%d node_exec_counts=%s retry_wall_ms=%s trace=%s"
                  % (attempts, json.dumps(ctx["counts"], sort_keys=True), elapsed_ms,
                     json.dumps(st["trace"])))
        return {"ok": True, "attempts": attempts, "error_text": "injected transient failure",
                "results": st["verified"], "out": out}

    raise ValueError("unsupported mode: %s" % mode)


if __name__ == "__main__":
    # 一次性构图开销（与端到端读数分开量，见报告 §4 M3）
    for kind, fan in (("linear", False), ("fanout", True)):
        t0 = time.perf_counter()
        app = _build(fanout=fan)
        print("COMPILE_%s_MS %.3f" % (kind.upper(), (time.perf_counter() - t0) * 1000.0))
        # M2「编排单元数」：直接读编译后图的节点/边结构，而不是数源码行
        gg = app.get_graph()
        print("GRAPH_%s nodes=%d edges=%d node_names=%s"
              % (kind.upper(), len(gg.nodes), len(gg.edges),
                 json.dumps(sorted(gg.nodes.keys()), ensure_ascii=False)))
    print("CAPS %s" % json.dumps(CAPS, ensure_ascii=False, sort_keys=True))
