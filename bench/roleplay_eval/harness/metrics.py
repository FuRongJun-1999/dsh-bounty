#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一量尺（CONTRACT §4）：字符/字节/摘要、激活集差异、逆序对、配对自助法 CI。

纯函数，无 I/O。自助法固定 seed=0、2000 次重采样。
本文件同时是 §7.2 读数行的唯一构造处：适配器、运行器、基线都从这里出串。
"""

from __future__ import annotations

import hashlib
import json
import random
import sys

BOOTSTRAP_ITERS = 2000
BOOTSTRAP_SEED = 0
ALPHA = 0.05


def chars(s):
    """Unicode 码点数（Python len）。"""
    return len(s)


def bytes_of(s):
    """UTF-8 字节数。"""
    return len(s.encode("utf-8"))


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def fmt_uids(uids):
    """§7.2：空集合写 -。"""
    xs = sorted(int(u) for u in uids)
    return ",".join(str(u) for u in xs) if xs else "-"


def join_uids(seq):
    """保序连接：注入顺序是读数，不得排序。空集合写 -。"""
    xs = [int(u) for u in seq]
    return ",".join(str(u) for u in xs) if xs else "-"


def parse_uids(token):
    t = (token or "").strip()
    if t in ("", "-"):
        return []
    return [int(x) for x in t.split(",")]


def diff_sets(a, b):
    """返回 (only_a, only_b, same)：对称差两侧 ＋ 交集大小。"""
    sa, sb = set(a), set(b)
    return sorted(sa - sb), sorted(sb - sa), len(sa & sb)


def inversion_count(order):
    """逆序对数：i<j 且 order[i]>order[j] 的个数。"""
    n = 0
    for i in range(len(order)):
        for j in range(i + 1, len(order)):
            if order[i] > order[j]:
                n += 1
    return n


def percentile(xs, q):
    """最近秩法：sorted[min(n-1, round(q*(n-1)))]。"""
    s = sorted(xs)
    if not s:
        raise ValueError("percentile: 空序列")
    idx = int(round(q * (len(s) - 1)))
    return s[min(len(s) - 1, max(0, idx))]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def paired_bootstrap_ci(pairs, iters=BOOTSTRAP_ITERS, seed=BOOTSTRAP_SEED, alpha=ALPHA):
    """配对自助法 95% CI。pairs=[(a,b)]，统计量＝mean(a-b)。固定 seed，逐次可复现。"""
    deltas = [float(a) - float(b) for a, b in pairs]
    if not deltas:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(deltas)
    stats = []
    for _ in range(iters):
        acc = 0.0
        for _ in range(n):
            acc += deltas[rng.randrange(n)]
        stats.append(acc / n)
    return (percentile(stats, alpha / 2.0), percentile(stats, 1.0 - alpha / 2.0))


def fmt_num(x):
    f = float(x)
    if f == int(f):
        return str(int(f))
    return "%.6g" % f


# ---- §7.2 读数行 ----

def readout_line(adapter, profile, turn, active_uids, inject_order, chars_n, bytes_n, dropped_uids):
    return "READOUT %s %s turn=%d active=%d order=%s chars=%d bytes=%d dropped=%s" % (
        adapter, profile, turn, len(active_uids), join_uids(inject_order),
        int(chars_n), int(bytes_n), fmt_uids(dropped_uids))


def diff_line(a, b, profile, turn, set_a, set_b):
    only_a, only_b, same = diff_sets(set_a, set_b)
    return "DIFF %s %s %s turn=%d only_a=%s only_b=%s same=%d" % (
        a, b, profile, turn, fmt_uids(only_a), fmt_uids(only_b), same)


def kpi_line(metric, value, ci, n):
    return "KPI %s value=%s ci=[%s,%s] n=%d" % (
        metric, fmt_num(value), fmt_num(ci[0]), fmt_num(ci[1]), int(n))


def sha_line(digest, path):
    return "SHA %s file=%s" % (digest, path)


def determinism_line(adapter, repeats, identical, digest):
    return "DETERMINISM %s repeats=%d identical=%s sha=%s" % (
        adapter, int(repeats), "true" if identical else "false", digest)


def timing_line(adapter, profile, min_ms, p50_ms, p95_ms):
    return "TIMING %s profile=%s min_ms=%s p50_ms=%s p95_ms=%s" % (
        adapter, profile, fmt_num(min_ms), fmt_num(p50_ms), fmt_num(p95_ms))


def caps_line(adapter, caps):
    return "CAPS %s %s" % (adapter, json.dumps(caps, ensure_ascii=False,
                                               sort_keys=True, separators=(",", ":")))


def unsupported_line(adapter, field, reason):
    return "UNSUPPORTED %s field=%s reason=%s" % (adapter, field, reason)


def error_line(adapter, profile, kind):
    return "ERROR %s profile=%s kind=%s" % (adapter, profile, kind)


# ---- 自检 ----

def selftest():
    checks = []
    assert chars("下雨") == 2 and bytes_of("下雨") == 6
    checks.append("chars/bytes")
    assert sha256_text("") == ("e3b0c44298fc1c149afbf4c8996fb924"
                               "27ae41e4649b934ca495991b7852b855")
    checks.append("sha256")
    assert fmt_uids([]) == "-" and fmt_uids([3, 1, 2]) == "1,2,3"
    assert parse_uids("-") == [] and parse_uids("2,1") == [2, 1]
    assert join_uids([3, 1]) == "3,1" and join_uids([]) == "-"
    checks.append("uid-format")
    assert diff_sets([1, 2, 3], [2, 3, 4]) == ([1], [4], 2)
    checks.append("diff-sets")
    assert inversion_count([]) == 0 and inversion_count([1, 2, 3]) == 0
    assert inversion_count([3, 2, 1]) == 3 and inversion_count([2, 1, 3]) == 1
    checks.append("inversion")
    assert percentile([1, 2, 3, 4], 0.5) == 3
    checks.append("percentile")
    ci1 = paired_bootstrap_ci([(5, 4), (5, 4), (5, 4)])
    ci2 = paired_bootstrap_ci([(5, 4), (5, 4), (5, 4)])
    assert ci1 == ci2 == (1.0, 1.0), ci1
    ci3 = paired_bootstrap_ci([(9, 1), (1, 9), (5, 5), (7, 3)], iters=200)
    assert ci3[0] <= ci3[1]
    checks.append("bootstrap-determinism")
    print("SELFTEST metrics checks=%d ok" % len(checks))
    print(readout_line("baseline", "P0", 1, [1, 2], [2, 1], 81, 243, []))
    print(diff_line("baseline", "sillytavern", "P0", 1, [1, 2, 3], [2, 3, 4]))
    print(kpi_line("M1_active_delta", 0.5, paired_bootstrap_ci([(2, 1), (3, 3), (1, 0)]), 3))
    print(timing_line("baseline", "P0", 41.2, 42.0, 55.5))
    print(determinism_line("baseline", 8, True, sha256_text("x")))
    print(caps_line("baseline", {"at_depth": True, "recursive": True}))
    print(unsupported_line("baseline", "regex_key", "baseline-literal-key"))
    print(sha_line(sha256_text("x"), "out/baseline_P0.json"))
    print(error_line("baseline", "P0", "exit-1"))
    print("OK selftest")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    print("用法：python -X utf8 metrics.py --selftest")
    raise SystemExit(2)
