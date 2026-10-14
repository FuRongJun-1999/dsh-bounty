"""cross-eval 被测方案 3/3：txtai Workflow（任务管道）。

被测引擎：txtai 9.14.0 的 txtai.workflow（Task 管道 + Workflow 编排）。
五个步骤全部调用 bench/cross_eval/harness/workload.py 的纯函数，检索算法与基线
及其它引擎完全一致（公平性规则见 harness/spec.md:37-41）。

每一步用到的引擎 API（中文注释贯穿全文）：
- 编排：txtai.workflow.Workflow(tasks=[...], workers=N)。元素先由
  Workflow.chunk（base.py:125-154）分批，每批依次穿过 tasks（base.py:156-174
  的 Workflow.process）。
- 单元：txtai.workflow.Task(action=[fn], unpack=True)。元素用 txtai 约定的
  (id, data, tag) 三元组，Task.filteredrun（task/base.py:99-132）取出 data 交给
  action；action 收到的是整批 data 组成的 list，且必须返回「每个输入元素一项」的 list
  （否则 filteredpack 的 results[ids.index(x)] 会 IndexError，见 task/base.py:152）。
- 数据流：整条流水线只用 1 个元素承载运行状态（state dict），5 个 Task 依次改写它，
  这是 txtai「任务管道」的直译用法。
- 扇出：Task(action=[a0..aN], concurrency="thread") + Workflow(workers=N)。
  txtai 的并发原语作用域是「同一 Task 内的多个 action」（task/base.py:296-297 ->
  execute.py:239 的 len(args) > 1 -> execute.py:258-262 的 ThreadPool），
  没有数据元素级扇出。因此 parallel 模式把 40 条查询按连续分片交给 N 个 action，
  并发由 txtai 自己的线程池提供（不是本文件自写线程池）。
- 检查点/恢复：txtai Workflow 无检查点 API（见 raw/txtai_capability_probe.txt）。
- 重试：Task 无重试参数（Task(retries=3) 抛 TypeError，见 raw 日志）。
"""

import os
import sys
import threading

# runner 会把 harness 目录插进 sys.path；这里再兜一次，便于单独跑本文件。
_HERE = os.path.dirname(os.path.abspath(__file__))
_HARNESS = os.path.normpath(os.path.join(_HERE, os.pardir, "harness"))
if _HARNESS not in sys.path:
    sys.path.insert(0, _HARNESS)

import workload  # noqa: E402

# 引擎入口：只用 workflow 子包（父包 txtai/__init__.py 仍会被导入，冷启动代价见报告 M3）
from txtai.workflow import Task, Workflow  # noqa: E402

NAME = "txtai"

CAPS = {
    # 无检查点 / 无恢复：txtai/workflow/ 全目录 grep -ri 'checkpoint|resume|restart' 0 命中，
    # Workflow 也没有 save/load 状态持久化 API。
    "checkpoint": False,
    # 无内建重试：Task 不接受 retries 参数。
    "retry": False,
    # 有并发原语，但作用域是「Task 内多 action」，不是数据元素。
    "fanout": True,
    "note": ("fanout=True 指 txtai 内建线程/进程池（task/base.py:296-297 -> execute.py:239/258-262），"
             "作用域为同一 Task 内的多个 action，无元素级扇出；"
             "checkpoint=False（workflow/ 目录 grep checkpoint|resume|restart 0 命中，Workflow 无 save/load）；"
             "retry=False（Task(retries=3) -> TypeError: __init__() got unexpected keyword arguments: 'retries'）"),
}

STEPS = ("load", "index", "retrieve", "verify", "emit")

# 证据行只打印一次，避免 runner 的 timeit（1 预热 + 7 次）刷屏
_PRINTED = set()


def _say_once(key, line):
    if key not in _PRINTED:
        _PRINTED.add(key)
        print(line, flush=True)


class _Run:
    """一次流水线运行的共享上下文 + 真实执行轨迹。

    轨迹不硬编码：每个节点 action 进入时调用 record，因此
    trace / counts 都是真实执行留下的证据。
    """

    def __init__(self, cfg, fail_at_verify=0, transient_failures=0):
        self.cfg = cfg
        self.corpus_path = cfg["corpus"]
        self.out_path = cfg["out"]
        self.k = cfg.get("k", workload.K_TOP)
        self.docs = None
        self.bm25_index = None
        self.verified = None

        self.lock = threading.Lock()
        self.trace = []          # 每次节点执行追加一条（含重复）
        self.counts = {}         # 步骤 -> 真实执行次数
        self.threads = {}        # 步骤 -> 参与执行的线程 id 集合

        # 注入计划（用于 resume / retry 的受控失败）
        self.fail_at_verify = fail_at_verify         # >0：第 N 次进入 verify 时抛错
        self.transient_failures = transient_failures  # 前 N 次 verify 抛瞬时错
        self.verify_entries = 0
        self.first_error = None

    # ---- 轨迹 ----
    def record(self, step):
        with self.lock:
            self.trace.append(step)
            self.counts[step] = self.counts.get(step, 0) + 1
            self.threads.setdefault(step, set()).add(threading.get_ident())

    def step_trace(self):
        """把逐次执行的原始轨迹压成「步骤序列」（只去掉相邻重复）。"""
        out = []
        for s in self.trace:
            if not out or out[-1] != s:
                out.append(s)
        return out

    # ---- 五个步骤（全部调用 workload 的纯函数）----
    def step_load(self, batch):
        # Task action 收到整批元素（本设计恒为 1 个 state）；本步是全局步，结果写进 state。
        self.record("load")
        state = batch[0]
        self.docs = workload.step_load(self.corpus_path)          # workload.step_load
        state["docs"] = self.docs
        return batch

    def step_index(self, batch):
        self.record("index")
        state = batch[0]
        self.bm25_index = workload.step_index(state["docs"])      # workload.step_index
        state["index"] = self.bm25_index
        return batch

    def step_retrieve(self, batch):
        # 单 action 路径：整批查询一次交给 workload.step_retrieve（顺序执行）。
        self.record("retrieve")
        state = batch[0]
        state["retrieved"] = workload.step_retrieve(state["index"], state["queries"], self.k)
        return batch

    def shard_retrieve(self, i, n, batch):
        """parallel 模式的第 i 个 action：只处理自己的连续分片。

        连续分片保证「按 action 顺序拼接」可以还原原始查询顺序
        （execute.py:242 的 starmap 保序）。
        """
        self.record("retrieve")
        state = batch[0]
        queries = state["queries"]
        size = -(-len(queries) // n)          # ceil
        part = queries[i * size:(i + 1) * size]
        return {"state": state, "shard": i, "size": len(part),
                "retrieved": workload.step_retrieve(state["index"], part, self.k)}

    def retrieve_actions(self, n):
        """构造 n 个 action，交给同一个 Task 并发执行（txtai 的扇出原语）。"""
        actions = []
        for i in range(n):
            def action(batch, _i=i):
                # action 必须返回「每个输入元素一项」的 list；这里只有 1 个元素 -> 返回 1 项。
                return [self.shard_retrieve(_i, n, batch)]
            actions.append(action)
        return actions

    def step_verify(self, batch):
        self.verify_entries += 1
        # 受控注入：resume 第 1 次进入 verify 抛错；retry 前 transient_failures 次抛瞬时错。
        if self.fail_at_verify and self.verify_entries == self.fail_at_verify:
            raise RuntimeError("injected failure at verify")
        if self.transient_failures and self.verify_entries <= self.transient_failures:
            raise RuntimeError("injected transient failure")

        self.record("verify")
        # parallel 模式下，retrieve 的 N 个 action 输出被 txtai 的 hstack 合并成 1 个
        # (s0, s1, ..., sN) 元组挂在同一个元素上（task/base.py:444-472 -> 227-250）。
        if len(batch) == 1 and isinstance(batch[0], tuple):
            parts = batch[0]
            state = parts[0]["state"]
            retrieved = []
            for shard in parts:
                retrieved.extend(shard["retrieved"])
            state["retrieved"] = retrieved
        else:
            state = batch[0]
            retrieved = state["retrieved"]
        self.verified = workload.step_verify(state["index"], retrieved)   # workload.step_verify
        state["verified"] = self.verified
        return [state]

    def step_emit(self, batch):
        self.record("emit")
        item = batch[0]
        state = item[0]["state"] if isinstance(item, tuple) else item
        workload.step_emit(state["verified"], self.out_path)              # workload.step_emit
        return [state]


def _build_workflow(run, parallel, workers):
    """把五个步骤装成 txtai Workflow 的 5 个 Task（编排单元数 = 5）。"""
    tasks = [
        Task(action=[run.step_load], unpack=True),      # Task: 管道单元
        Task(action=[run.step_index], unpack=True),
    ]
    if parallel and workers > 1:
        # 多 action + concurrency="thread" -> txtai 的 ThreadPool 扇出
        tasks.append(Task(action=run.retrieve_actions(workers), concurrency="thread", unpack=True))
    else:
        tasks.append(Task(action=[run.step_retrieve], unpack=True))
    tasks += [
        Task(action=[run.step_verify], unpack=True),
        Task(action=[run.step_emit], unpack=True),
    ]
    return Workflow(tasks=tasks, workers=workers if (parallel and workers > 1) else None)


def _elements(cfg):
    """喂给 Workflow 的元素：txtai 约定的 (id, data, tag) 三元组，data 是运行状态。"""
    state = {"queries": workload.load_queries(cfg["queries"]),
             "docs": None, "index": None, "retrieved": None, "verified": None}
    return [(0, state, "run")]


def _execute(run, elements, parallel, workers):
    wf = _build_workflow(run, parallel, workers)
    return list(wf(elements))       # Workflow.__call__ 是生成器，list() 强制跑完


def run(mode, cfg):
    workers = int(cfg.get("workers", 4) or 4)

    if mode in ("normal", "sequential", "parallel"):
        parallel = mode == "parallel" and workers > 1
        run_ctx = _Run(cfg)
        elements = _elements(cfg)
        _execute(run_ctx, elements, parallel, workers)
        if parallel:
            tids = sorted(run_ctx.threads.get("retrieve", set()))
            _say_once("fanout", "TXTAT_FANOUT mode=parallel actions=%d workers=%d "
                                "retrieve_invocations=%d distinct_threads=%d thread_ids=%s"
                                % (workers, workers, run_ctx.counts.get("retrieve", 0), len(tids), tids))
        return {"ok": True, "trace": run_ctx.step_trace(), "workers": workers if parallel else 1,
                "results": run_ctx.verified, "out": cfg["out"]}

    if mode == "resume":
        # 真实执行轨迹：第 1 遍在 verify 前抛错 -> 引擎抛到调用方（本文件只负责重新驱动）。
        run_ctx = _Run(cfg, fail_at_verify=1)
        elements = _elements(cfg)
        try:
            _execute(run_ctx, elements, False, 1)
        except RuntimeError as e:
            run_ctx.first_error = str(e)
        else:
            raise AssertionError("注入失败未生效")
        before = dict(run_ctx.counts)
        _say_once("resume", "TXTAT_CAPABILITY checkpoint=unsupported "
                            "evidence='txtai 9.14.0: grep -ri checkpoint|resume|restart txtai/workflow/ -> 0 hits; "
                            "Workflow has no save/load'; recovery=rerun_whole_workflow "
                            "first_pass_counts=%s" % (before,))
        # 恢复路径：txtai 无检查点，只能整段重跑（与基线同）；名单来自真实计数。
        run_ctx.fail_at_verify = 0
        _execute(run_ctx, elements, False, 1)
        reexec = [s for s in STEPS if run_ctx.counts.get(s, 0) > 1]
        _say_once("resume2", "TXTAT_RESTART counts=%s raw_trace=%s reexecuted=%s"
                             % (run_ctx.counts, run_ctx.trace, reexec))
        return {"ok": True, "trace": run_ctx.step_trace(), "first_error": run_ctx.first_error,
                "steps_reexecuted_after_failure": reexec,
                "results": run_ctx.verified, "out": cfg["out"],
                "note": ("不支持检查点/恢复（依据：txtai 9.14.0 txtai/workflow/ 全目录 "
                         "grep -ri 'checkpoint|resume|restart' 0 命中；Workflow 无 save/load；"
                         "Workflow(checkpoint=True) -> TypeError）。"
                         "恢复=整段重跑 Workflow，重跑名单来自真实节点执行计数 %s" % run_ctx.counts)}

    if mode == "retry":
        run_ctx = _Run(cfg, transient_failures=2)
        elements = _elements(cfg)
        attempts = 0
        while True:
            attempts += 1                      # 真实尝试次数 = 真实驱动 Workflow 的次数
            try:
                _execute(run_ctx, elements, False, 1)
                break
            except RuntimeError as e:
                run_ctx.first_error = str(e)
                continue
        _say_once("retry", "TXTAT_CAPABILITY retry=unsupported "
                           "evidence=\"Task(retries=3) -> TypeError: __init__() got unexpected keyword arguments: 'retries'\"; "
                           "attempts=%d verify_entries=%d counts=%s"
                           % (attempts, run_ctx.verify_entries, run_ctx.counts))
        return {"ok": True, "attempts": attempts, "error_text": "injected transient failure",
                "trace": run_ctx.step_trace(),
                "results": run_ctx.verified, "out": cfg["out"],
                "note": ("引擎无内建重试（依据：txtai 9.14.0 Task 不接受 retries 参数，"
                         "Task(retries=3) -> TypeError: __init__() got unexpected keyword arguments: 'retries'；"
                         "txtai/workflow/ 目录 grep -ri 'retry|backoff' 0 命中）。"
                         "本模式由调用方重新驱动整个 Workflow，attempts 为真实尝试次数")}

    raise ValueError("unsupported mode: %s" % mode)
