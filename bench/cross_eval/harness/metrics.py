"""读数工具：计时、指纹、行数统计。所有读数都落原始文本，报告里只引用原文。"""
import hashlib
import json
import os
import statistics
import time


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def loc(path):
    """非空、非注释行数（# 开头）。"""
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                n += 1
    return n


def timeit(fn, repeats=7, warmup=1):
    """同机交替对照用：返回 p50/p95/min（毫秒）。"""
    for _ in range(warmup):
        fn()
    xs = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1000.0)
    xs.sort()
    return {"n": len(xs), "min_ms": round(xs[0], 3),
            "p50_ms": round(statistics.median(xs), 3),
            "p95_ms": round(xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))], 3)}


def jdump(obj, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, sort_keys=True, indent=1)
        f.write("\n")
    return path
