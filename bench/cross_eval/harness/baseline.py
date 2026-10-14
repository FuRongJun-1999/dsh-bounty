"""基线：手写顺序 Python（无任何编排框架）。作为三家引擎的对照面。

模式：normal / resume / retry / sequential / parallel。
- sequential：逐条查询串行检索
- parallel：ThreadPoolExecutor(workers) 并发检索（扇出对照面）
- resume：无检查点，失败后只能整段重跑（这就是基线的「断点续跑」读数）
- retry：注入与重试分离（注入只负责造错，重试只由**有界**循环负责），尝试上限
         MAX_ATTEMPTS；超限不静默继续，回报 ok=False + first_error。
         修前是 `while True` 无上限（defect P1-07：被重试步骤真抛错时永不返回）。
- 读数：trace / steps_reexecuted_after_failure 一律由**真实执行**推导（_Stages），
        不用字面量自述（defect P0-02：修前两者都是硬编码字面量）。
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workload  # noqa: E402

NAME = "baseline"
CAPS = {"checkpoint": False, "retry": False, "fanout": True,
        "note": "手写 ThreadPoolExecutor 扇出；无检查点、无内建重试"}

#: 五步的规范顺序（重跑名单按它排序，保证确定性）
STAGE_ORDER = ["load", "index", "retrieve", "verify", "emit"]

#: retry 模式的尝试上限：与对照面三家引擎同口径
#: （langgraph `RetryPolicy(max_attempts=3)`、llamaindex `stop_after_attempt(3)`）。
MAX_ATTEMPTS = 3
#: 注入的瞬时失败次数。注入只负责造错，**不**负责重试；被重试步骤的真实异常
#: 与注入异常走同一条有界路径。可用 cfg["transient_failures"] 覆盖。
TRANSIENT_FAILURES = 2
#: retry 档「被重试单元」的账本标签：只喂 _Stages.reexecuted()，**不进** trace
#: （trace 是阶段轨迹，不是重试计数器）。
RETRY_LEDGER = "retry:verify"


class _Stages:
    """一次运行的真实阶段轨迹与计数。

    为什么需要它：resume 档原先的 trace 与 steps_reexecuted_after_failure 都是**字面量**，
    与真实执行不符（实测：真实阶段计数全 1，自述却称 load/index/retrieve 被重跑）；
    retry 档原先也自述 attempts。读数一律由本类推导，不再自述。

    两个账本刻意分开：
    - trace()      —— 只记**阶段**（STAGE_ORDER 里的五步）的逐次执行，即真实执行序列；
    - done(step)   —— 记**任意被重试单元**的真实完成次数（含不在 STAGE_ORDER 里的名字，
                      例如 retry 档的被重试单元）；它只喂 reexecuted()，
                      **不进** trace，免得把内部标签混进阶段轨迹。
    """

    def __init__(self):
        self.seq = []
        self.counts = {}

    def mark(self, step):
        """记一次**阶段**执行（进 trace，也进计数）。"""
        self.seq.append(step)
        self.done(step)

    def done(self, step):
        """只记次数、不进 trace：给不在 STAGE_ORDER 里的被重试单元用。"""
        self.counts[step] = self.counts.get(step, 0) + 1

    def trace(self):
        return list(self.seq)

    def count(self, step):
        return self.counts.get(step, 0)

    def reexecuted(self):
        """真实执行计数 > 1 的单元：按 STAGE_ORDER 排序，不在表里的排在后面（按名字）。

        - 正常档 / resume 档：去重的阶段名单（如 ["load","index","retrieve"]）；
        - retry 档：**被重试单元**的账本标签（RETRY_LEDGER）展开成真跑了几次
          （attempts=3 ⇒ ["verify","verify"]，attempts=1 ⇒ []）。
          用独立标签而不是直接数 verify 阶段，是为了让「阶段轨迹」与「重试计数」解耦：
          trace 里 verify 只出现一次（第 4 步），重试次数由账本承载。
        """
        extra = sorted(s for s in self.counts
                       if s not in STAGE_ORDER and s != RETRY_LEDGER)
        out = [s for s in STAGE_ORDER if self.counts.get(s, 0) > 1]
        for _ in range(max(0, self.counts.get(RETRY_LEDGER, 0) - 1)):
            out.append("verify")
        return out + extra


def _load_index(cfg, st):
    st.mark("load")
    docs = workload.step_load(cfg["corpus"])
    st.mark("index")
    return workload.step_index(docs), workload.load_queries(cfg["queries"])


def _fanout(index, queries, cfg, workers, st):
    st.mark("retrieve")
    k = cfg.get("k", workload.K_TOP)
    if workers <= 1:
        return [workload.step_retrieve(index, [q], k)[0] for q in queries]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda q: workload.step_retrieve(index, [q], k)[0], queries))


def _finish(index, retrieved, cfg, st):
    st.mark("verify")
    verified = workload.step_verify(index, retrieved)
    st.mark("emit")
    workload.step_emit(verified, cfg["out"])
    return verified


def _verify_attempt(index, retrieved, state, transient_failures):
    """被重试单元的一次真实调用——state["calls"] 就是真实调用计数，不另设计数器。

    注入放在这里，是为了让「假造的瞬时失败」与「步骤真的抛错」共用一个入口：
    两者都表现为这次调用抛出 RuntimeError，重试上限对两者一视同仁。
    """
    state["calls"] += 1
    if state["calls"] <= transient_failures:
        raise RuntimeError("injected transient failure")
    return workload.step_verify(index, retrieved)


def run(mode, cfg):
    out = cfg["out"]
    st = _Stages()
    if mode in ("normal", "sequential", "parallel"):
        index, queries = _load_index(cfg, st)
        workers = 1 if mode == "sequential" else (cfg.get("workers", 4) if mode == "parallel" else 1)
        retrieved = _fanout(index, queries, cfg, workers, st)
        verified = _finish(index, retrieved, cfg, st)
        return {"ok": True, "trace": st.trace(),
                "workers": workers, "results": verified, "out": out}
    if mode == "resume":
        # 第一遍：跑到 verify 之前失败。无检查点 ⇒ 这一遍的产物全部作废。
        index, queries = _load_index(cfg, st)
        retrieved = _fanout(index, queries, cfg, 1, st)
        try:
            raise RuntimeError("injected failure at verify")
        except RuntimeError as e:
            first_error = str(e)
        # 第二遍：**真的整段重跑**（这才是「无检查点」的真实代价，不是自述）。
        index, queries = _load_index(cfg, st)
        retrieved = _fanout(index, queries, cfg, 1, st)
        verified = _finish(index, retrieved, cfg, st)
        return {"ok": True, "trace": st.trace(),
                "first_error": first_error,
                "steps_reexecuted_after_failure": st.reexecuted(),
                "results": verified, "out": out}
    if mode == "retry":
        index, queries = _load_index(cfg, st)
        retrieved = _fanout(index, queries, cfg, 1, st)
        # 注入与重试分离：注入（_verify_attempt）只负责造错，重试只由下面这个**有界**
        # 循环负责。被重试步骤真的抛 RuntimeError 时走同一上限，超限**不**静默继续。
        max_attempts = int(cfg.get("max_attempts", MAX_ATTEMPTS))
        transient = int(cfg.get("transient_failures", TRANSIENT_FAILURES))
        state = {"calls": 0}
        first_error = None
        verified = None
        # verify 是**被重试的阶段**：trace 里只记一次（第 4 步），重试次数记在
        # 「被重试单元」的完成账本（RETRY_LEDGER）上——_Stages.reexecuted() 会把它
        # 展开成真跑了几次（["verify"] * (attempts-1)），trace 不被内部标签污染。
        st.mark("verify")
        while state["calls"] < max_attempts:
            st.done(RETRY_LEDGER)
            try:
                verified = _verify_attempt(index, retrieved, state, transient)
                break
            except RuntimeError as exc:
                if first_error is None:
                    first_error = str(exc)
        attempts = state["calls"]          # 由真实调用计数推导，不是独立计数器
        reexec = st.reexecuted()
        if verified is None:
            first_error = first_error or "retry exhausted without a recorded error"
            return {"ok": False, "attempts": attempts, "first_error": first_error,
                    "error_text": first_error,
                    "trace": st.trace(),
                    "steps_reexecuted_after_failure": reexec,
                    "results": [], "out": out}
        # emit：verify 已经在上面记过（重试阶段只记一次），所以这里只补 emit。
        st.mark("emit")
        workload.step_emit(verified, out)
        return {"ok": True, "attempts": attempts, "error_text": "injected transient failure",
                "trace": st.trace(),
                "steps_reexecuted_after_failure": reexec,
                "results": verified, "out": out}
    raise ValueError("unsupported mode: %s" % mode)
