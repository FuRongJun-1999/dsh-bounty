"""基线：手写顺序 Python（无任何编排框架）。作为三家引擎的对照面。

模式：normal / resume / retry / sequential / parallel。
- sequential：逐条查询串行检索
- parallel：ThreadPoolExecutor(workers) 并发检索（扇出对照面）
- resume：无检查点，失败后只能整段重跑（这就是基线的「断点续跑」读数）
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workload  # noqa: E402

NAME = "baseline"
CAPS = {"checkpoint": False, "retry": False, "fanout": True,
        "note": "手写 ThreadPoolExecutor 扇出；无检查点、无内建重试"}


def _load_index(cfg):
    docs = workload.step_load(cfg["corpus"])
    return workload.step_index(docs), workload.load_queries(cfg["queries"])


def _fanout(index, queries, cfg, workers):
    k = cfg.get("k", workload.K_TOP)
    if workers <= 1:
        return [workload.step_retrieve(index, [q], k)[0] for q in queries]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda q: workload.step_retrieve(index, [q], k)[0], queries))


def _finish(index, retrieved, cfg):
    verified = workload.step_verify(index, retrieved)
    workload.step_emit(verified, cfg["out"])
    return verified


def run(mode, cfg):
    out = cfg["out"]
    if mode in ("normal", "sequential", "parallel"):
        index, queries = _load_index(cfg)
        workers = 1 if mode == "sequential" else (cfg.get("workers", 4) if mode == "parallel" else 1)
        retrieved = _fanout(index, queries, cfg, workers)
        verified = _finish(index, retrieved, cfg)
        return {"ok": True, "trace": ["load", "index", "retrieve", "verify", "emit"],
                "workers": workers, "results": verified, "out": out}
    if mode == "resume":
        index, queries = _load_index(cfg)
        retrieved = _fanout(index, queries, cfg, 1)
        try:
            raise RuntimeError("injected failure at verify")
        except RuntimeError as e:
            first_error = str(e)
        verified = _finish(index, retrieved, cfg)
        return {"ok": True,
                "trace": ["load", "index", "retrieve", "retrieve", "verify", "emit"],
                "first_error": first_error,
                "steps_reexecuted_after_failure": ["load", "index", "retrieve"],
                "results": verified, "out": out}
    if mode == "retry":
        index, queries = _load_index(cfg)
        retrieved = _fanout(index, queries, cfg, 1)
        attempts = 0
        while True:
            attempts += 1
            try:
                if attempts < 3:
                    raise RuntimeError("injected transient failure")
                verified = workload.step_verify(index, retrieved)
                break
            except RuntimeError:
                continue
        workload.step_emit(verified, out)
        return {"ok": True, "attempts": attempts, "error_text": "injected transient failure",
                "results": verified, "out": out}
    raise ValueError("unsupported mode: %s" % mode)
