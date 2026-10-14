# -*- coding: utf-8 -*-
"""tests/test_cross_eval_baseline_readout.py —— 基线读数与重试的守卫件（PR-A 合入件）。

## 被守卫的两条缺陷（同一份 `bench/cross_eval/harness/baseline.py`）

1. **读数自述**（P0-02）：resume 档的 `trace` / `steps_reexecuted_after_failure` 曾是**字面量**，
   且 resume 分支捕获注入异常后**直接继续**（没有重跑）。实测修前：真实阶段计数全 1，
   自报却称 load/index/retrieve 被重跑（读数来源：`P0-02/repro/raw/before.txt`，逐字见 PR-A/CHANGES.md）。
   `bench/cross_eval/systems/llamaindex_impl.py` 的 `_run_resume` 的 `trace` 同为字面量。
2. **重试无上限**（P1-07）：`run("retry")` 曾是 `while True` ＋ `except RuntimeError: continue`，
   被重试步骤真抛错时**永不返回**；`ATTEMPTS 3` 是 `if attempts < 3: raise` **假造注入**的产物
   （读数来源：`P1-07/repro/raw/before.txt`）。

## 判据（40 条，每条一个稳定 id；末行「通过 N / 失败 M」）

- A 组 动态（纯标准库 ＋ 桩）：resume 的真实阶段计数/真实执行序列 vs 自报读数；retry 的有界性、
  真实尝试次数、超限判读、注入面可配置。
- B 组 源码面：不得有 `while True` / 吞异常的 `continue`；尝试次数必须由真实调用计数推导。
- C 组 AST：四家 `run`/`_run_resume` 返回的读数**不得**是字面量列表（langgraph / txtai 对照面不得误报）。
- D 组 口径与版本面：`harness/spec.md` 写明口径；llamaindex 的 `trace` 由真实序列推导。
- E 组 端到端（子进程 ＋ 产物 sha256）：注入路径 attempts==3 ∧ 产物等于黄金；超限路径不静默成功；
  正常/顺序/并发三档**零行为变更**（产物 sha256 与 trace 与冻结读数一致）。
- F 组 自证判别力：`--mutate` 对每条判据做定点变异。

**子进程 ＋ 超时**：E 组的「恒抛时必须有界」场景跑在子进程里（父进程兜底超时），守卫自己不会被
被测实现的死循环挂住（修前的 `while True` 正是这种情形）。

用法：
  python -B -X utf8 tests/test_cross_eval_baseline_readout.py            # 正向：末行「通过 N / 失败 M」
  python -B -X utf8 tests/test_cross_eval_baseline_readout.py --quiet    # 只输出 RED <id> 与末行
  python -B -X utf8 tests/test_cross_eval_baseline_readout.py --mutate   # 定点变异自证（要求已打补丁）
  python -B -X utf8 tests/test_cross_eval_baseline_readout.py --root <仓根>
退出码：0 全绿；1 有红项；2 环境/用法错误（缺 baseline.py 或黄金产物指纹不符）。
只用标准库、不联网、不需要 numpy/rank_bm25（检索层用「从黄金产物反推」的桩替换）。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)

REPO_REL = os.path.join("bench", "cross_eval")
HARNESS_REL = os.path.join(REPO_REL, "harness")
DATA_REL = os.path.join(REPO_REL, "data")
GOLDEN_REL = os.path.join(DATA_REL, "out_baseline.jsonl")

BASELINE_REL = os.path.join(HARNESS_REL, "baseline.py")
SPEC_REL = os.path.join(HARNESS_REL, "spec.md")
LI_REL = os.path.join(REPO_REL, "systems", "llamaindex_impl.py")

#: 四家的读数面（AST 判据用）；llamaindex 的 resume 读数在 _run_resume 里
IMPLS = [(os.path.join(HARNESS_REL, "baseline.py"), ("run",)),
         (os.path.join(REPO_REL, "systems", "langgraph_impl.py"), ("run",)),
         (os.path.join(REPO_REL, "systems", "llamaindex_impl.py"), ("_run_resume",)),
         (os.path.join(REPO_REL, "systems", "txtai_impl.py"), ("run",))]
READOUT_KEYS = ("trace", "steps_reexecuted_after_failure")
CONTRAST = ("langgraph_impl.py", "txtai_impl.py")

STAGE_ORDER = ["load", "index", "retrieve", "verify", "emit"]
TRACE_NORMAL = ["load", "index", "retrieve", "verify", "emit"]
RESUME_TRACE = ["load", "index", "retrieve", "load", "index", "retrieve", "verify", "emit"]
RESUME_REEXEC = ["load", "index", "retrieve"]

#: 运行预算：子进程被重试单元的预算 / 父进程兜底超时（秒）
WORKER_BUDGET_S = 5.0
PARENT_TIMEOUT_S = 60.0
EXPECT_MAX_ATTEMPTS = 3

#: 端到端场景表：case id → (mode, cfg 追加, 桩, 说明)
CASES = [
    ("injected", "retry", {}, None, "冻结的「假造两次瞬时失败」路径（不打桩）"),
    ("hang", "retry", {"scenario": "hang"}, "hang", "恒抛 RuntimeError 的桩 ＋ 默认注入"),
    ("hang_no_inject", "retry", {"scenario": "hang", "transient_failures": 0}, "hang",
     "恒抛 RuntimeError 的桩（关闭注入＝真实异常）"),
    ("flaky", "retry", {"scenario": "flaky", "transient_failures": 0}, "flaky",
     "真实瞬时失败：桩前 2 次抛、第 3 次成功（关闭注入）"),
    ("clean", "retry", {"scenario": "count", "transient_failures": 0}, "count",
     "无失败（关闭注入，只计真实调用）"),
    ("normal", "normal", {}, None, "对照面：不得被本次合并改动"),
    ("sequential", "sequential", {}, None, "对照面：不得被本次合并改动"),
    ("parallel", "parallel", {}, None, "对照面：不得被本次合并改动"),
    ("resume", "resume", {}, None, "读数面：真实计数推导"),
]
CASES_BY_ID = {c[0]: c for c in CASES}

QUIET = False
pass_n = 0
fail_n = 0
reds = []


def check(aid, title, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
        if not QUIET:
            print("[✓] %s %s — %s" % (aid, title, detail))
    else:
        fail_n += 1
        reds.append(aid)
        print("RED %s %s — %s" % (aid, title, detail))


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scratch_dir(prefix):
    """可写临时目录：优先系统 tempfile（本机由 TEMP/TMP 指到可写处），失败退到本包的 _scratch。"""
    try:
        p = tempfile.mkdtemp(prefix=prefix)
        probe = os.path.join(p, ".probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return p
    except Exception:
        p = os.path.join(HERE, "_scratch_guard_pra")
        os.makedirs(p, exist_ok=True)
        return p


def load_harness(root):
    """按路径加载 harness/baseline.py（连带 workload），不依赖 sys.path 里的同名模块。"""
    harness = os.path.join(root, HARNESS_REL)
    if harness not in sys.path:
        sys.path.insert(0, harness)
    import importlib.util as ilu
    mods = {}
    for name in ("workload", "baseline"):
        sys.modules.pop(name, None)
        spec = ilu.spec_from_file_location(name, os.path.join(harness, name + ".py"))
        mod = ilu.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        mods[name] = mod
    return mods["workload"], mods["baseline"]


def stub_retrieval(workload, golden):
    """纯标准库的检索层桩：从黄金产物**反推**语料/索引/检索，让 verify/emit 走真函数。

    关键约束：**同一个 doc id 会被多条查询命中**（黄金里 doc0014 出现在 q000/q003…），
    而 verify 是「该文档的正文是否含全部查询词」的**逐文档**判据。所以合成语料按 id 建
    **一份**文档，正文 = 所有引用它的查询词的并集（含自己的 id）；verify 的真函数在这份
    语料上对黄金的每条查询都必然得出 golden 的 ids / dropped。
    检索层直接按黄金的 ids 顺序返回（真实 BM25 的 top-5 顺序），于是产物 sha256 可与黄金逐字节比对，
    而本守卫不需要 numpy / rank_bm25。
    """
    by_id, mapping, queries = {}, {}, []
    for i, g in enumerate(golden):
        terms = [str(t) for t in g["terms"]]
        kept = [str(x) for x in g["ids"]]
        for did in kept:
            by_id.setdefault(did, set()).update(terms)
        bogus = ["zz-bogus-%03d-%d" % (i, j) for j in range(int(g["dropped"]))]
        for bid in bogus:
            by_id.setdefault(bid, [])           # 失败候选：正文里一个查询词都没有
        rec = {"q": str(g["q"]), "terms": terms, "ids": kept + bogus}
        mapping[rec["q"]] = rec
        queries.append({"q": rec["q"], "terms": terms})
    docs = []
    for did in sorted(by_id):
        words = by_id[did]
        # list(...) 去重后再排序：保证同一份黄金产物每次合成出**同一份**语料（确定性）
        terms = sorted(set(words)) if isinstance(words, set) else []
        docs.append({"id": did, "topic": "t00", "text": " ".join([did] + terms)})
    workload.step_load = lambda path: list(docs)
    workload.step_index = lambda d: {"docs": list(d), "bm25": None}
    workload.step_retrieve = lambda index, qs, k=workload.K_TOP: [dict(mapping[q["q"]]) for q in qs]
    # 每读一次查询表就把桩的映射重建一次（变异体可能改了语料/查询，避免用陈旧映射 KeyError）
    workload.load_queries = lambda path: [dict(mapping[q["q"]]) for q in queries]
    return docs, queries


# --------------------------------------------------------------- 子进程：场景读数

def child_main(case, root, outdir):
    """在一个子进程里跑一个场景，打印一行 GUARD_CHILD {json} 后 os._exit(0)。

    被重试单元跑在**前台线程**里并设预算：拿不到返回值也照样打印读数 ⇒ 父进程能判读。
    """
    _case, mode, extra, scenario, _why = CASES_BY_ID[case]
    extra = dict(extra)
    extra.pop("scenario", None)
    harness = os.path.join(root, HARNESS_REL)
    data = os.path.join(root, DATA_REL)
    golden_path = os.path.join(data, "out_baseline.jsonl")
    if not os.path.isfile(golden_path):
        print("GUARD_CHILD " + json.dumps({"case": case, "fatal": "缺 data/out_baseline.jsonl"}))
        sys.stdout.flush()
        os._exit(0)
    with open(golden_path, "r", encoding="utf-8") as f:
        golden = [json.loads(ln) for ln in f if ln.strip()]

    workload, _baseline_ignored = load_harness(root)
    stub_retrieval(workload, golden)
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("impl_pr_a_guard_%s" % case,
                                       os.path.join(harness, "baseline.py"))
    baseline = ilu.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    # 注意：上面这一步会把 **同一个** workload 再 exec 一遍（spec 名相同 ⇒ 同一模块对象），
    # 这会重置 stub。因此桩的装载顺序是「先 import baseline，再打桩」。
    workload, baseline = load_harness(root)
    stub_retrieval(workload, golden)
    real_verify = workload.step_verify

    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, "out_%s.jsonl" % case)
    if os.path.isfile(out_path):
        os.remove(out_path)

    counters = {"calls": 0}
    if scenario == "hang":
        def stub(index, retrieved):
            counters["calls"] += 1
            raise RuntimeError("persistent failure in step_verify")
        workload.step_verify = stub
    elif scenario == "flaky":
        def stub(index, retrieved):
            counters["calls"] += 1
            if counters["calls"] <= 2:
                raise RuntimeError("transient step_verify failure #%d" % counters["calls"])
            return real_verify(index, retrieved)
        workload.step_verify = stub
    elif scenario == "count":
        def stub(index, retrieved):
            counters["calls"] += 1
            return real_verify(index, retrieved)
        workload.step_verify = stub

    cfg = {"corpus": os.path.join(data, "corpus.jsonl"),
           "queries": os.path.join(data, "queries.jsonl"),
           "out": out_path, "workers": 4, "k": workload.K_TOP}
    cfg.update(extra)

    box = {}

    def target():
        try:
            box["r"] = baseline.run(mode, cfg)
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = "%s: %s" % (type(exc).__name__, exc)

    t0 = time.perf_counter()
    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(WORKER_BUDGET_S)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    rec = {"case": case, "mode": mode, "scenario": scenario or "",
           "returned": not th.is_alive(), "elapsed_ms": round(elapsed_ms, 1),
           "stub_calls": counters["calls"], "worker_budget_s": WORKER_BUDGET_S,
           "golden_sha256": sha256_file(golden_path),
           "product_sha256": sha256_file(out_path) if os.path.isfile(out_path) else None}
    r = box.get("r")
    if isinstance(r, dict):
        rec["present"] = sorted(r.keys())
        for k in ("ok", "attempts", "error_text", "first_error",
                  "trace", "steps_reexecuted_after_failure"):
            rec[k] = r.get(k)
        rec["results_n"] = len(r.get("results") or [])
    if "exc" in box:
        rec["exception"] = box["exc"]
    print("GUARD_CHILD " + json.dumps(rec, ensure_ascii=False, sort_keys=True))
    sys.stdout.flush()
    os._exit(0)


def run_child(case, root, outdir):
    cmd = [sys.executable, "-B", "-X", "utf8", os.path.abspath(__file__),
           "--child", case, "--root", root, "--outdir", outdir]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=PARENT_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or ""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        return {"case": case, "parent_timeout": True,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 1),
                "stdout_tail": raw.strip().splitlines()[-1:]}
    line = ""
    for ln in (p.stdout or "").splitlines():
        if ln.startswith("GUARD_CHILD "):
            line = ln
    if not line:
        return {"case": case, "no_reading": True, "rc": p.returncode,
                "stdout_tail": (p.stdout or "").strip().splitlines()[-2:],
                "stderr_tail": (p.stderr or "").strip().splitlines()[-3:]}
    try:
        rec = json.loads(line[len("GUARD_CHILD "):])
        rec["rc"] = p.returncode
        return rec
    except ValueError as exc:
        return {"case": case, "no_reading": True, "parse_error": str(exc),
                "stdout_tail": [line[:200]]}


def collect(root, outdir):
    readings = {}
    for case, _m, _e, _s, _why in CASES:
        readings[case] = run_child(case, root, outdir)
    return readings


def usable(r):
    return bool(r) and not r.get("parent_timeout") and not r.get("no_reading")


def bad(readings, case, head):
    r = readings.get(case) or {}
    if r.get("parent_timeout"):
        return "case=%s 的子进程未在 %.0fs 内给出读数 ⇒ 判红并点名该 case" % (case, PARENT_TIMEOUT_S)
    if r.get("no_reading"):
        return "case=%s 无读数（rc=%s，stderr 尾部 %s）" % (
            case, r.get("rc"), str(r.get("stderr_tail"))[:160])
    if r.get("fatal"):
        return "case=%s 环境错误：%s" % (case, r["fatal"])
    return head


def describe(r):
    bits = ["%.1fms" % r.get("elapsed_ms", -1), "返回" if r.get("returned") else "未返回"]
    if r.get("exception"):
        bits.append("抛出 %s" % r["exception"])
    if r.get("stub_calls") is not None:
        bits.append("桩调用 %s" % r["stub_calls"])
    if "attempts" in r:
        bits.append("attempts=%s" % r["attempts"])
    return "，".join(bits)


def jdump(x):
    return json.dumps(x, ensure_ascii=False)


# --------------------------------------------------------------- A 组：源码面

def src_of(root, rel):
    p = os.path.join(root, rel)
    if not os.path.isfile(p):
        return None
    return read_text(p)


def a10(root):
    """AST 判据：不得有 `while True`（无上限重试），也不得有「捕获 RuntimeError 后既不做
    事也不记错」的处理器（`except RuntimeError: continue` 这种吞异常）。

    刻意用 AST 而不是子串：docstring 里就写着修前的 `while True`（那是证据，不是实现）。
    """
    t = src_of(root, BASELINE_REL)
    if t is None:
        return False, "找不到 %s" % BASELINE_REL.replace(os.sep, "/")
    tree = ast.parse(t)
    loops = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.While) and isinstance(n.test, ast.Constant)
             and n.test.value is True]
    silent = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.ExceptHandler):
            continue
        if n.name is None:
            continue
        names = {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}
        if n.name not in names:         # 捕获了但连错误对象都没碰过 ⇒ 吞掉
            silent.append(n.lineno)
    ok = (not loops) and (not silent)
    detail = []
    if loops:
        detail.append("while True 在 L%s" % loops)
    if silent:
        detail.append("捕获后未记录错误的 except 在 L%s" % silent)
    return ok, ("；".join(detail) if detail else "无 while True、无吞异常的 except")


def a11(root):
    t = src_of(root, BASELINE_REL) or ""
    return ("state[\"calls\"] += 1" in t) and ("attempts = state[\"calls\"]" in t), \
        "attempts 由真实调用计数 state['calls'] 推导"


def a12(root):
    t = src_of(root, BASELINE_REL) or ""
    return ("ok\": False" in t) and ("first_error" in t), \
        "有明确的超限失败返回（ok=False ＋ first_error）"


def a13(root):
    """口径：_Stages 两个账本分开——mark 进 trace，done 只计数（防「done 混进 trace」的回归）。"""
    t = src_of(root, BASELINE_REL) or ""
    return (("def mark(self, step):" in t) and ("def done(self, step):" in t)
            and ("self.seq.append(step)" in t)), \
        "_Stages.mark 记阶段序列、done 只记账（trace 不被内部标签污染）"


# --------------------------------------------------------------- A 组：动态面

def a01(root, work):
    workload, baseline = load_harness(root)
    counts, seq = {}, []

    def wrap(mod, name, key):
        orig = getattr(mod, name)

        def inner(*a, **k):
            counts[key] = counts.get(key, 0) + 1
            seq.append(key)
            return orig(*a, **k)
        setattr(mod, name, inner)

    # 检索/校验的重活全部换桩：只保留「哪个阶段被执行、执行几次」这一事实（零第三方依赖）
    workload.step_index = lambda docs: {"docs": docs, "bm25": None}
    workload.step_retrieve = lambda index, queries, k=5: [
        {"q": q.get("q", ""), "terms": q.get("terms", []), "ids": []} for q in queries]
    workload.step_verify = lambda index, retrieved: [dict(r, dropped=0) for r in retrieved]
    workload.step_emit = lambda verified, out: out
    wrap(workload, "step_load", "load")
    wrap(workload, "step_index", "index")
    wrap(workload, "step_verify", "verify")
    wrap(workload, "step_emit", "emit")
    wrap(baseline, "_fanout", "retrieve")

    out = os.path.join(work, "resume_out.jsonl")
    cfg = {"corpus": os.path.join(root, DATA_REL, "corpus.jsonl"),
           "queries": os.path.join(root, DATA_REL, "queries.jsonl"),
           "out": out, "workers": 1, "k": 5}
    r = baseline.run("resume", cfg)
    stage = {s: counts.get(s, 0) for s in STAGE_ORDER}
    derived = [s for s in STAGE_ORDER if stage[s] > 1]
    reported = list(r.get("steps_reexecuted_after_failure") or [])
    return (reported == derived), \
        "真实重跑名单=%s vs 自报=%s" % (jdump(derived), jdump(reported))


def a02(root, work):
    workload, baseline = load_harness(root)
    seq = []

    def wrap(mod, name, key):
        orig = getattr(mod, name)

        def inner(*a, **k):
            seq.append(key)
            return orig(*a, **k)
        setattr(mod, name, inner)

    workload.step_index = lambda docs: {"docs": docs, "bm25": None}
    workload.step_retrieve = lambda index, queries, k=5: [
        {"q": q.get("q", ""), "terms": q.get("terms", []), "ids": []} for q in queries]
    workload.step_verify = lambda index, retrieved: [dict(r, dropped=0) for r in retrieved]
    workload.step_emit = lambda verified, out: out
    wrap(workload, "step_load", "load")
    wrap(workload, "step_index", "index")
    wrap(workload, "step_verify", "verify")
    wrap(workload, "step_emit", "emit")
    wrap(baseline, "_fanout", "retrieve")

    out = os.path.join(work, "resume_trace.jsonl")
    cfg = {"corpus": os.path.join(root, DATA_REL, "corpus.jsonl"),
           "queries": os.path.join(root, DATA_REL, "queries.jsonl"),
           "out": out, "workers": 1, "k": 5}
    r = baseline.run("resume", cfg)
    return (list(r.get("trace") or []) == seq), \
        "自报 trace=%s vs 真实执行序列=%s" % (jdump(r.get("trace")), jdump(seq))


def a03(root, work):
    workload, baseline = load_harness(root)
    counts, seq = {}, []

    def wrap(mod, name, key):
        orig = getattr(mod, name)

        def inner(*a, **k):
            counts[key] = counts.get(key, 0) + 1
            seq.append(key)
            return orig(*a, **k)
        setattr(mod, name, inner)

    workload.step_index = lambda docs: {"docs": docs, "bm25": None}
    workload.step_retrieve = lambda index, queries, k=5: [
        {"q": q.get("q", ""), "terms": q.get("terms", []), "ids": []} for q in queries]
    workload.step_verify = lambda index, retrieved: [dict(r, dropped=0) for r in retrieved]
    workload.step_emit = lambda verified, out: out
    wrap(workload, "step_load", "load")
    wrap(workload, "step_index", "index")
    wrap(workload, "step_verify", "verify")
    wrap(workload, "step_emit", "emit")
    wrap(baseline, "_fanout", "retrieve")

    out = os.path.join(work, "resume_rerun.jsonl")
    cfg = {"corpus": os.path.join(root, DATA_REL, "corpus.jsonl"),
           "queries": os.path.join(root, DATA_REL, "queries.jsonl"),
           "out": out, "workers": 1, "k": 5}
    r = baseline.run("resume", cfg)
    real_verify = counts.get("verify", 0)
    # 「无检查点 ⇒ 产物那一遍才作数」：第一遍的 load/index/retrieve 必须真的跑了两遍
    ok = (counts.get("load") == 2 and counts.get("index") == 2 and counts.get("retrieve") == 2
          and real_verify == 1 and counts.get("emit") == 1
          and bool(r.get("first_error")))
    return ok, "真实计数=%s first_error=%r" % (
        jdump({s: counts.get(s, 0) for s in STAGE_ORDER}), r.get("first_error"))


def a04(root, work):
    """不碰真实检索：把检索层换成桩，只测 retry 的上限（零第三方依赖）。"""
    workload, baseline = load_harness(root)
    with open(os.path.join(root, GOLDEN_REL), "r", encoding="utf-8") as f:
        golden = [json.loads(ln) for ln in f if ln.strip()]
    stub_retrieval(workload, golden)
    cfg = {"corpus": os.path.join(root, DATA_REL, "corpus.jsonl"),
           "queries": os.path.join(root, DATA_REL, "queries.jsonl"),
           "out": os.path.join(work, "retry_min.jsonl"), "workers": 4, "k": workload.K_TOP,
           "transient_failures": 0, "max_attempts": 1}
    r = baseline.run("retry", cfg)
    return (r.get("ok") is True and r.get("attempts") == 1), \
        "ok=%r attempts=%r（max_attempts=1 ⇒ 只该试一次）" % (r.get("ok"), r.get("attempts"))


def a05(root, work):
    workload, baseline = load_harness(root)
    with open(os.path.join(root, GOLDEN_REL), "r", encoding="utf-8") as f:
        golden = [json.loads(ln) for ln in f if ln.strip()]
    stub_retrieval(workload, golden)
    cfg = {"corpus": os.path.join(root, DATA_REL, "corpus.jsonl"),
           "queries": os.path.join(root, DATA_REL, "queries.jsonl"),
           "out": os.path.join(work, "retry_bad.jsonl"), "workers": 4,
           "k": workload.K_TOP, "transient_failures": 9, "max_attempts": 2}
    r = baseline.run("retry", cfg)
    return (r.get("ok") is False and r.get("attempts") == 2
            and bool(str(r.get("first_error") or "").strip())), \
        "ok=%r attempts=%r first_error=%r" % (r.get("ok"), r.get("attempts"), r.get("first_error"))


# --------------------------------------------------------------- C 组：AST

def _literal_readouts(path, fnames):
    """返回 [(函数名, 行号, 键, 值节点)]：函数体里 return {..., "trace": <字面量列表>}。"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        tree = ast.parse(f.read())
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name not in fnames:
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                for k, v in zip(node.value.keys, node.value.values):
                    if isinstance(k, ast.Constant) and k.value in READOUT_KEYS:
                        if isinstance(v, ast.List) and all(isinstance(e, ast.Constant) for e in v.elts):
                            out.append((fn.name, node.lineno, k.value, v))
    return out


def _all_literal_hits(root):
    hits = []
    for rel, fns in IMPLS:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            continue
        for fname, lineno, key, _v in _literal_readouts(p, fns):
            hits.append("%s:%s()L%d %s" % (rel.replace(os.sep, "/"), fname, lineno, key))
    return hits


def c01(root):
    hits = _all_literal_hits(root)
    return (hits == []), ("字面量命中：%s" % jdump(hits)) if hits else "四家 resume/normal 读数都不是字面量"


def c02(root):
    hits = [h for h in _all_literal_hits(root) if "baseline.py" in h]
    return (hits == []), ("baseline 字面量命中：%s" % jdump(hits)) if hits else "baseline 无字面量读数"


def c03(root):
    hits = [h for h in _all_literal_hits(root) if "llamaindex_impl.py" in h]
    return (hits == []), ("llamaindex 字面量命中：%s" % jdump(hits)) if hits else "llamaindex 无字面量读数"


def c04(root):
    hits = [h for h in _all_literal_hits(root) if any(c in h for c in CONTRAST)]
    return (hits == []), ("对照面被误报：%s" % jdump(hits)) if hits else "langgraph/txtai 未被误报"


def _readout_nodes(path, fnames):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        tree = ast.parse(f.read())
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name not in fnames:
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                for k, v in zip(node.value.keys, node.value.values):
                    if isinstance(k, ast.Constant) and k.value in READOUT_KEYS:
                        out.append((fn.name, node.lineno, k.value, v))
    return out


def c05(root):
    p = os.path.join(root, LI_REL)
    if not os.path.isfile(p):
        return False, "找不到 systems/llamaindex_impl.py"
    nodes = [n for n in _readout_nodes(p, ("_run_resume",)) if n[2] == "trace"]
    if not nodes:
        return False, "llamaindex._run_resume 的返回体里没有 trace 读数"
    kinds = [type(v).__name__ for _f, _l, _k, v in nodes]
    return (all(k not in ("List", "Tuple", "Constant") for k in kinds)), \
        "trace 值节点类型=%s（须为表达式，不能是字面量）" % jdump(kinds)


# --------------------------------------------------------------- D 组：口径

def d01(root):
    t = src_of(root, SPEC_REL)
    if t is None:
        return False, "找不到 harness/spec.md"
    return ("真实执行序列" in t and "真实执行计数" in t), "spec.md「读数项」写明了 trace / 重跑名单口径"


def d02(root):
    t = src_of(root, SPEC_REL) or ""
    return (("attempts" in t) and ("真实调用次数" in t)), \
        "spec.md 写明 attempts = 被重试单元的真实调用次数（不是循环轮次自报）"


# --------------------------------------------------------------- E 组：子进程端到端

def e01(readings):
    r = readings.get("injected") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "injected", "注入路径必须在有限时间内返回")
    ok = (r.get("ok") is True and r.get("attempts") == EXPECT_MAX_ATTEMPTS)
    return ok, "ok=%r attempts=%r（期望 True / %d）" % (r.get("ok"), r.get("attempts"),
                                                     EXPECT_MAX_ATTEMPTS)


def e02(readings):
    r = readings.get("injected") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "injected", "注入路径必须在有限时间内返回")
    if "trace" not in (r.get("present") or []):
        return False, "注入路径返回体没有 trace（产物面之外的读数面缺失）"
    want = {"load", "index", "retrieve", "verify", "emit"}
    got = set(r.get("trace") or [])
    return (got == want and "emit" in got), "trace=%s" % jdump(r.get("trace"))


def e03(readings):
    r = readings.get("injected") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "injected", "注入路径必须在有限时间内返回")
    return (r.get("product_sha256") == r.get("golden_sha256")), \
        "产物 sha256=%s golden=%s" % (str(r.get("product_sha256"))[:16], str(r.get("golden_sha256"))[:16])


def e04(readings):
    r = readings.get("injected") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "injected", "注入路径必须在有限时间内返回")
    return (r.get("error_text") == "injected transient failure"), \
        "error_text=%r" % r.get("error_text")


def e05(readings):
    r = readings.get("hang") or {}
    if not usable(r):
        return False, bad(readings, "hang", "")
    if not r.get("returned"):
        return False, ("run(\"retry\") 未在 %.1fs 内返回/抛出（桩被调用 %s 次，恒抛 RuntimeError "
                       "⇒ 无界重试）" % (WORKER_BUDGET_S, r.get("stub_calls")))
    return True, "hang 场景 " + describe(r)


def e06(readings):
    r = readings.get("hang") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "hang", "该判据需要 hang 场景在有限时间内给出读数")
    att, calls = r.get("attempts"), (r.get("stub_calls") or 0)
    if att is None:
        return False, "返回体没有 attempts 读数（桩调用 %s）" % calls
    return (att <= EXPECT_MAX_ATTEMPTS and calls <= EXPECT_MAX_ATTEMPTS), \
        "attempts=%s、桩调用=%s（上限 %d）" % (att, calls, EXPECT_MAX_ATTEMPTS)


def e07(readings):
    r = readings.get("hang") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "hang", "该判据需要 hang 场景在有限时间内给出读数")
    if r.get("exception"):
        return True, "抛出可判读异常：%s" % r["exception"]
    if r.get("ok") is False and str(r.get("first_error") or "").strip():
        return True, "ok=False，first_error=%r" % r["first_error"]
    return False, "既没抛异常也不是 ok=False ＋ first_error（ok=%r first_error=%r）⇒ 静默成功" % (
        r.get("ok"), r.get("first_error"))


def e08(readings):
    r = readings.get("hang_no_inject") or {}
    if not usable(r):
        return False, bad(readings, "hang_no_inject", "")
    if not r.get("returned"):
        return False, ("关闭注入后（被重试步骤就是恒抛的桩）run(\"retry\") 未在 %.1fs 内返回"
                       "（桩被调用 %s 次）" % (WORKER_BUDGET_S, r.get("stub_calls")))
    return True, "hang_no_inject 场景 " + describe(r)


def e09(readings):
    r = readings.get("hang_no_inject") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "hang_no_inject", "该判据需要该场景在有限时间内给出读数")
    if (r.get("stub_calls") or 0) != EXPECT_MAX_ATTEMPTS:
        return False, "真实异常只被调用 %s 次（期望 == %d）" % (r.get("stub_calls"),
                                                          EXPECT_MAX_ATTEMPTS)
    if r.get("exception"):
        return True, "抛出可判读异常：%s" % r["exception"]
    if r.get("ok") is not False or not str(r.get("first_error") or "").strip():
        return False, "没有明确失败：ok=%r first_error=%r" % (r.get("ok"), r.get("first_error"))
    if "persistent failure in step_verify" not in str(r.get("first_error")):
        return False, "first_error=%r 不是真实错误文本" % r.get("first_error")
    if "emit" in (r.get("trace") or []):
        return False, "失败了却声称走到 emit（trace=%s）" % jdump(r.get("trace"))
    return True, "ok=False、first_error 是真实错误、trace 无 emit（%s）" % jdump(r.get("trace"))


def e10(readings):
    r = readings.get("flaky") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "flaky", "该判据需要该场景在有限时间内给出读数")
    ok = (r.get("stub_calls") == EXPECT_MAX_ATTEMPTS
          and r.get("attempts") == r.get("stub_calls"))
    return ok, "stub=%s attempts=%s" % (r.get("stub_calls"), r.get("attempts"))


def e11(readings):
    r = readings.get("flaky") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "flaky", "该判据需要该场景在有限时间内给出读数")
    return (r.get("product_sha256") == r.get("golden_sha256")), \
        "产物 sha256=%s golden=%s" % (str(r.get("product_sha256"))[:16], str(r.get("golden_sha256"))[:16])


def e12(readings):
    r = readings.get("flaky") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "flaky", "该判据需要该场景在有限时间内给出读数")
    att = r.get("attempts")
    want = ["verify"] * max(0, att - 1)
    got = r.get("steps_reexecuted_after_failure")
    if got != want:
        return False, "重跑名单=%s（期望 %s = attempts-1 个 verify）" % (jdump(got), jdump(want))
    return True, "重跑名单 %s 与 attempts=%s 一致" % (jdump(got), att)


def e13(readings):
    r = readings.get("clean") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "clean", "该判据需要该场景在有限时间内给出读数")
    ok = (r.get("ok") is True and r.get("attempts") == 1 and r.get("stub_calls") == 1
          and r.get("steps_reexecuted_after_failure") == []
          and r.get("product_sha256") == r.get("golden_sha256"))
    return ok, "ok=%r attempts=%r 桩调用=%r 重跑名单=%s" % (
        r.get("ok"), r.get("attempts"), r.get("stub_calls"),
        jdump(r.get("steps_reexecuted_after_failure")))


def e14(readings):
    r = readings.get("resume") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "resume", "该判据需要该场景在有限时间内给出读数")
    ok = (r.get("ok") is True and r.get("trace") == RESUME_TRACE
          and r.get("first_error") == "injected failure at verify"
          and "attempts" not in (r.get("present") or []))
    return ok, "trace=%s first_error=%r present=%s" % (
        jdump(r.get("trace")), r.get("first_error"), jdump(r.get("present")))


def e15(readings):
    r = readings.get("resume") or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, "resume", "该判据需要该场景在有限时间内给出读数")
    ok = (r.get("steps_reexecuted_after_failure") == RESUME_REEXEC
          and r.get("trace") == RESUME_TRACE)
    return ok, "重跑名单=%s" % jdump(r.get("steps_reexecuted_after_failure"))


def _mode_golden(readings, case, mode):
    r = readings.get(case) or {}
    if not usable(r) or not r.get("returned"):
        return False, bad(readings, case, "%s 档需要该场景在有限时间内给出读数" % mode)
    problems = []
    if r.get("ok") is not True:
        problems.append("ok=%r" % r.get("ok"))
    if r.get("product_sha256") != r.get("golden_sha256"):
        problems.append("产物 sha256=%s ≠ 黄金=%s" % (str(r.get("product_sha256"))[:16],
                                                  str(r.get("golden_sha256"))[:16]))
    if r.get("trace") != TRACE_NORMAL:
        problems.append("trace=%s（期望 %s）" % (jdump(r.get("trace")), jdump(TRACE_NORMAL)))
    return (not problems), "；".join(problems) if problems else "%s 零行为变更（产物黄金、trace 一致）" % mode


def e16(readings):
    return _mode_golden(readings, "normal", "normal")


def e17(readings):
    return _mode_golden(readings, "sequential", "sequential")


def e18(readings):
    return _mode_golden(readings, "parallel", "parallel")


ASSERTIONS = [
    ("A1", "resume 真实重跑名单 == 自报 steps_reexecuted_after_failure", "dyn", a01),
    ("A2", "resume 自报 trace == 真实执行序列（含两遍）", "dyn", a02),
    ("A3", "resume 真的整段重跑：load/index/retrieve 各 2 次、verify/emit 各 1 次", "dyn", a03),
    ("A4", "retry max_attempts=1 ⇒ attempts == 1（上限真的生效）", "dyn", a04),
    ("A5", "retry 注入 9 次 / 上限 2 ⇒ ok=False ∧ attempts==2 ∧ first_error 非空", "dyn", a05),
    ("A6", "baseline.py 无 while True、无吞 RuntimeError 后 continue", "src", a10),
    ("A7", "attempts 由真实调用计数 state['calls'] 推导", "src", a11),
    ("A8", "有明确的超限失败返回（ok=False ＋ first_error）", "src", a12),
    ("A9", "_Stages：mark 记序列、done 只记账（trace 不被内部标签污染）", "src", a13),
    ("C1", "四家 run/_run_resume 的 trace / 重跑名单不得是字面量（AST）", "ast", c01),
    ("C2", "baseline 不得有字面量读数", "ast", c02),
    ("C3", "llamaindex 不得有字面量读数", "ast", c03),
    ("C4", "对照面 langgraph / txtai 不得被误报", "ast", c04),
    ("C5", "llamaindex._run_resume 的 trace 是表达式", "ast", c05),
    ("D1", "spec.md 写明 trace / 重跑名单口径", "ast", d01),
    ("D2", "spec.md 写明 attempts = 真实调用次数", "ast", d02),
    ("E1", "注入路径 ok=True ∧ attempts == 3（子进程）", "child", e01),
    ("E2", "注入路径返回体含 trace（读数面在位）", "child", e02),
    ("E3", "注入路径产物 sha256 == 黄金", "child", e03),
    ("E4", "注入路径 error_text 在位", "child", e04),
    ("E5", "恒抛桩 ⇒ run(\"retry\") 有限时间内返回或抛出", "child", e05),
    ("E6", "恒抛桩 ⇒ attempts 与桩调用都 ≤ 3", "child", e06),
    ("E7", "恒抛桩 ⇒ 超限明确失败，不静默成功", "child", e07),
    ("E8", "关闭注入（真实异常）⇒ 同样终止", "child", e08),
    ("E9", "真实异常 ⇒ ok=False ∧ 桩真实调用 == 3 ∧ first_error 是真实错误 ∧ trace 无 emit", "child", e09),
    ("E10", "真实瞬时失败 ⇒ attempts == 桩调用 == 3", "child", e10),
    ("E11", "真实瞬时失败 ⇒ 产物黄金", "child", e11),
    ("E12", "重跑名单 == attempts-1 个 verify", "child", e12),
    ("E13", "无失败 ⇒ attempts == 桩调用 == 1 ∧ 重跑名单空 ∧ 产物黄金", "child", e13),
    ("E14", "resume 读数与冻结形态一致 ∧ 无 attempts 键", "child", e14),
    ("E15", "resume 重跑名单 == load/index/retrieve", "child", e15),
    ("E16", "normal 零行为变更（产物 sha256 ＋ trace）", "child", e16),
    ("E17", "sequential 零行为变更（产物 sha256 ＋ trace）", "child", e17),
    ("E18", "parallel 零行为变更（产物 sha256 ＋ trace）", "child", e18),
]

# --------------------------------------------------------------- 定点变异表
# 每条变异在**修后**的源码文本上做 count==1 的替换；expect 是它应打红的判据集合。
MUTATIONS = [
    {"id": "M01-resume-trace-literal",
     "why": "把 resume 的 trace 改回字面量自述（复现 P0-02 修前形态）",
     "rel": BASELINE_REL,
     "edits": [('        return {"ok": True, "trace": st.trace(),\n                "first_error": first_error,',
                '        return {"ok": True, "trace": ["load", "index", "retrieve", "retrieve", "verify", "emit"],\n                "first_error": first_error,')],
     "expect": ["A2", "C1", "C2", "E14", "E15"]},
    {"id": "M02-resume-reexec-empty",
     "why": "重跑名单恒为空（自述「什么都没重跑」，与真跑两遍不符）",
     "rel": BASELINE_REL,
     "edits": [('                "steps_reexecuted_after_failure": st.reexecuted(),',
                '                "steps_reexecuted_after_failure": [],')],
     "expect": ["A1", "C1", "C2", "E15"]},
    {"id": "M03-retry-infinite-loop",
     "why": "retry 改回 while True 无上限（复现 P1-07 修前形态）",
     "rel": BASELINE_REL,
     "edits": [('        while state["calls"] < max_attempts:',
                '        while True:')],
     "expect": ["A5", "A6", "E5", "E6", "E7", "E8", "E9"]},
    {"id": "M04-retry-silent-ok",
     "why": "超限后静默回报 ok=True（吞掉真实失败）",
     "rel": BASELINE_REL,
     "edits": [('            return {"ok": False, "attempts": attempts, "first_error": first_error,',
                '            return {"ok": True, "attempts": attempts, "first_error": first_error,')],
     "expect": ["A5", "A8", "E7", "E9"]},
    {"id": "M05-attempts-literal-3",
     "why": "attempts 硬编码成 3（冻结版「假造注入」的报数方式）",
     "rel": BASELINE_REL,
     "edits": [('        attempts = state["calls"]          # 由真实调用计数推导，不是独立计数器',
                '        attempts = 3')],
     "expect": ["A4", "A5", "A7", "E13"]},
    {"id": "M06-reexec-off-by-one",
     "why": "重跑名单多算一次（把只跑了 1 次的阶段也算作重跑）",
     "rel": BASELINE_REL,
     "edits": [('        out = [s for s in STAGE_ORDER if self.counts.get(s, 0) > 1]',
                '        out = [s for s in STAGE_ORDER if self.counts.get(s, 0) >= 1]')],
     "expect": ["A1", "E12", "E13", "E15"]},
    {"id": "M07-injection-off",
     "why": "默认注入次数改 0（注入面消失）",
     "rel": BASELINE_REL,
     "edits": [('        transient = int(cfg.get("transient_failures", TRANSIENT_FAILURES))',
                '        transient = 0')],
     "expect": ["A5", "E1", "E4"]},
    {"id": "M08-verify-mark-twice",
     "why": "被重试阶段在 trace 里被记两次（把重跑混进阶段轨迹）",
     "rel": BASELINE_REL,
     "edits": [('        st.mark("verify")\n        while state["calls"] < max_attempts:',
                '        st.mark("verify")\n        st.mark("verify")\n        while state["calls"] < max_attempts:')],
     "expect": ["E12", "E13"]},
    {"id": "M09-retry-emit-skip",
     "why": "retry 成功路径不写产物（写到 out + '.skipped'）",
     "rel": BASELINE_REL,
     "edits": [('        workload.step_emit(verified, out)',
                '        workload.step_emit(verified, out + ".skipped")')],
     "expect": ["E3", "E11", "E13"]},
    {"id": "M10-normal-trace-short",
     "why": "正常档 trace 少掉 emit（零行为变更面被抓）",
     "rel": BASELINE_REL,
     "edits": [('    st.mark("emit")\n    workload.step_emit(verified, cfg["out"])',
                '    workload.step_emit(verified, cfg["out"])')],
     "expect": ["A2", "E14", "E15", "E16", "E17", "E18"]},
    {"id": "M11-done-into-trace",
     "why": "done 也往 trace 里追加（内部标签污染阶段轨迹）",
     "rel": BASELINE_REL,
     "edits": [('    def done(self, step):\n        """只记次数、不进 trace：给不在 STAGE_ORDER 里的被重试单元用。"""\n        self.counts[step] = self.counts.get(step, 0) + 1',
                '    def done(self, step):\n        """只记次数、不进 trace：给不在 STAGE_ORDER 里的被重试单元用。"""\n        self.seq.append(step)\n        self.counts[step] = self.counts.get(step, 0) + 1')],
     "expect": ["A2", "E2", "E14", "E15", "E16", "E17", "E18"]},
    {"id": "M12-swallow-exception",
     "why": "except RuntimeError 后直接 continue（吞掉真实失败）",
     "rel": BASELINE_REL,
     "edits": [('            except RuntimeError as exc:\n                if first_error is None:\n                    first_error = str(exc)',
                '            except RuntimeError as exc:\n                continue')],
     "expect": ["A6", "E9", "E4"]},
    {"id": "M17-retry-ledger-off",
     "why": "重试账本不记（reexecuted 只剩阶段计数 ⇒ 重跑名单塌成 []）",
     "rel": BASELINE_REL,
     "edits": [('            st.done(RETRY_LEDGER)\n', '')],
     "expect": ["E12"]},
    {"id": "M13-resume-no-rerun",
     "why": "resume 不整段重跑（第二遍删掉，退回「自述重跑」）",
     "rel": BASELINE_REL,
     "edits": [('        # 第二遍：**真的整段重跑**（这才是「无检查点」的真实代价，不是自述）。\n        index, queries = _load_index(cfg, st)\n        retrieved = _fanout(index, queries, cfg, 1, st)\n        verified = _finish(index, retrieved, cfg, st)',
                '        index, queries = _load_index(cfg, st)\n        verified = _finish(index, retrieved, cfg, st)')],
     "expect": ["A3", "E14", "E15"]},
    {"id": "M14-llamaindex-literal-trace",
     "why": "llamaindex 的 resume trace 改回字面量",
     "rel": LI_REL,
     "edits": [('            "trace": list(SEQ),',
                '            "trace": ["load", "index", "retrieve", "verify", "emit"],')],
     "expect": ["C1", "C3", "C5"]},
    {"id": "M15-retry-trace-empty",
     "why": "retry 的 trace 恒为空（读数面消失）",
     "rel": BASELINE_REL,
     "edits": [('        return {"ok": True, "attempts": attempts, "error_text": first_error or "",\n                "trace": st.trace(),',
                '        return {"ok": True, "attempts": attempts, "error_text": first_error or "",\n                "trace": [],')],
     "expect": ["C1", "C2", "E2"]},
    {"id": "M16-no-global-cap",
     "why": "默认上限放大到 10**12（等价恢复「无上限」）",
     "rel": BASELINE_REL,
     "edits": [('MAX_ATTEMPTS = 3', 'MAX_ATTEMPTS = 10 ** 12')],
     "expect": ["E5", "E6", "E7", "E8", "E9"]},
]

work_holder = {"dir": ""}


# --------------------------------------------------------------- 运行器

def _fmt(ok):
    return "[✓]" if ok else "[✘]"


def run_checks(root):
    work = work_holder["dir"]
    check("ENV", "黄金产物指纹可读（%s）" % GOLDEN_REL.replace(os.sep, "/"),
          os.path.isfile(os.path.join(root, GOLDEN_REL)), "")
    readings = collect(root, os.path.join(work, "out"))
    for aid, title, kind, fn in ASSERTIONS:
        try:
            if kind == "child":
                ok, detail = fn(readings)
            elif kind == "dyn":
                ok, detail = fn(root, work)
            else:
                ok, detail = fn(root)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, "断言自身异常 %s: %s" % (type(exc).__name__, exc)
        check(aid, title, ok, detail)


def _copy_tree(src_root, dst_root):
    for rel in (HARNESS_REL, DATA_REL, os.path.join(REPO_REL, "systems")):
        d = os.path.join(dst_root, rel)
        os.makedirs(os.path.dirname(d) or dst_root, exist_ok=True)
        shutil.copytree(os.path.join(src_root, rel), d)
    for dirpath, dirnames, _f in os.walk(dst_root):
        for d in list(dirnames):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirnames.remove(d)


def mutate_main(root, only=""):
    """定点变异自证：对修后副本逐条注入变异，断言**恰好**打红声明的判据集合。"""
    scratch = os.path.join(work_holder["dir"], "mut")
    os.makedirs(scratch, exist_ok=True)
    plan = [m for m in MUTATIONS if (not only or m["id"] == only)]
    if not plan:
        print("未知变异 id：%s" % only)
        return 2
    base = os.path.join(scratch, "base")
    _copy_tree(root, base)
    base_readings = collect(base, os.path.join(scratch, "out_base"))
    base_red = []
    for aid, _t, kind, fn in ASSERTIONS:
        try:
            if kind == "child":
                ok, _d = fn(base_readings)
            elif kind == "dyn":
                wd = os.path.join(scratch, "work_base")
                os.makedirs(wd, exist_ok=True)
                ok, _d = fn(base, wd)
            else:
                ok, _d = fn(base)
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            base_red.append(aid)
    if base_red:
        check("MUT-PRECOND", "未变异副本必须全绿（否则变异表无意义）", False,
              "未变异副本已红：%s" % jdump(base_red))
        print("通过 %d / 失败 %d" % (pass_n, fail_n))
        return 1

    for mut in plan:
        mid = mut["id"]
        mroot = os.path.join(scratch, mid)
        _copy_tree(root, mroot)
        path = os.path.join(mroot, mut["rel"])
        text = read_text(path)
        edit_ok, why = True, ""
        for old, new in mut["edits"]:
            n = text.count(old)
            if n != 1:
                edit_ok, why = False, "变异锚点命中 %d 次（要求恰好 1 次）：%r" % (n, old[:70])
                break
            text = text.replace(old, new, 1)
        if not edit_ok:
            check(mid, mut["why"], False, why)
            continue
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        mwork = os.path.join(scratch, "work_" + mid)
        os.makedirs(mwork, exist_ok=True)
        readings = collect(mroot, os.path.join(scratch, "out_" + mid))
        observed = []
        for aid, _t, kind, fn in ASSERTIONS:
            try:
                if kind == "child":
                    ok, _d = fn(readings)
                elif kind == "dyn":
                    ok, _d = fn(mroot, mwork)
                else:
                    ok, _d = fn(mroot)
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                observed.append(aid)
        want = sorted(mut["expect"])
        got = sorted(observed)
        check(mid, mut["why"], got == want,
              "observed=%s expected=%s %s" % (jdump(got), jdump(want), "OK" if got == want else "DIFF"))
    print("通过 %d / 失败 %d" % (pass_n, fail_n))
    return 1 if fail_n else 0


def main(argv=None):
    global QUIET
    ap = argparse.ArgumentParser(
        description="cross_eval 基线读数与重试的守卫件（resume 真实计数 ＋ retry 有上限）")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="仓根（默认本文件的上层目录）")
    ap.add_argument("--mutate", nargs="?", const="__all__", default=None,
                    help="定点变异自证（要求已打补丁）；可给一个变异 id 只跑那条")
    ap.add_argument("--list-mutations", action="store_true", help="列出变异 id 与其声明的红项集")
    ap.add_argument("--quiet", action="store_true", help="只输出 RED <id> 与末行")
    ap.add_argument("--child", default="", help="（内部）子进程场景 id")
    ap.add_argument("--outdir", default="", help="（内部）子进程产物目录")
    args = ap.parse_args(argv)
    QUIET = args.quiet

    root = os.path.abspath(args.root)
    if args.child:
        if args.child not in CASES_BY_ID:
            sys.stderr.write("未知 case：%s\n" % args.child)
            return 2
        return child_main(args.child, root, os.path.abspath(args.outdir or os.path.join(HERE, "_child")))

    if not os.path.isfile(os.path.join(root, BASELINE_REL)):
        sys.stderr.write("[guard] 环境错误：找不到 %s\n" % os.path.join(root, BASELINE_REL))
        return 2
    gp = os.path.join(root, GOLDEN_REL)
    if not os.path.isfile(gp):
        sys.stderr.write("[guard] 环境错误：找不到 %s\n" % gp)
        return 2

    work_holder["dir"] = scratch_dir("pra_guard_")
    try:
        if args.list_mutations:
            for m in MUTATIONS:
                print("%-26s expect=%s" % (m["id"], jdump(sorted(m["expect"]))))
            print("通过 %d / 失败 %d" % (len(MUTATIONS), 0))
            return 0
        if args.mutate is not None:
            return mutate_main(root, "" if args.mutate == "__all__" else args.mutate)
        print("检查根：%s" % root)
        print("— 断言 %d 条 / 定点变异 %d 条 —" % (len(ASSERTIONS), len(MUTATIONS)))
        run_checks(root)
        if QUIET:
            for aid in reds:
                print("RED %s" % aid)
        print("通过 %d / 失败 %d" % (pass_n, fail_n))
        return 1 if fail_n else 0
    finally:
        shutil.rmtree(work_holder["dir"], ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
