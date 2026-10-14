# -*- coding: utf-8 -*-
"""tests/test_check_reviews.py —— 守卫 scripts/check_reviews.py 的判别力自证。

做什么：把 docs/reviews/ 的真实交付集交给守卫跑一遍（正向必须全绿），
然后对**沙箱副本**逐个施加定点变异，断言**恰好**打红预期的那一条判据
（多红 = 判据语义纠缠；少红 = 该判据空转，等于没测）。

用法：
  python -X utf8 tests/test_check_reviews.py              # 末行「通过 N / 失败 M」
  python -X utf8 tests/test_check_reviews.py --quiet      # 只输出 RED <名> 与 RAN <n>
  python -X utf8 tests/test_check_reviews.py --mutate      # 只跑定点变异自证（全部，仓库体例）
  python -X utf8 tests/test_check_reviews.py --mutate=<id>  # 只跑一条变异，打印守卫的红项集
  python -X utf8 tests/test_check_reviews.py --root <dir>   # 指定被测树（开发用：合成夹具自证）
退出码：0 全绿；1 有失败项；2 变异锚点缺失（ANCHOR-MISS）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)
FENCE = chr(96) * 3
SCHEMES = ["LangGraph_v0.1.md", "LlamaIndex-Workflows_v0.1.md", "txtai-Workflow_v0.1.md"]
FAKE_SHA = "ab" * 32


class AnchorMiss(Exception):
    pass


def sub(path, old, new):
    t = read(path)
    if old not in t:
        raise AnchorMiss("%s 未命中锚点：%r" % (path, old[:60]))
    write(path, t.replace(old, new, 1))


def read(p):
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write(p, t):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(t)


def golden_sha(root):
    p = os.path.join(root, "bench", "cross_eval", "data", "out_baseline.jsonl")
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def report(root, i=0):
    return os.path.join(root, "docs", "reviews", SCHEMES[i])


def m_reorder_sections(root):
    t = read(report(root))
    i5 = t.index("## 5. 不适用条件")
    i6 = t.index("## 6. 未测项与原因")
    if i6 < i5:
        raise AnchorMiss("章节顺序已不是 5 在 6 前")
    write(report(root), t[:i5] + t[i6:] + t[i5:i6])


def m_fake_raw_ref(root):
    p = report(root)
    write(p, read(p) + "\n见 raw/not_exist_zzz.txt\n")


def m_invent_reading(root):
    p = report(root)
    line = "SHA %s golden=%s match=True lines=40" % (FAKE_SHA, golden_sha(root))
    write(p, read(p) + "\n" + FENCE + "\n" + line + "\n" + FENCE + "\n")


def m_judge_phrase(root):
    p = report(root)
    write(p, read(p) + "\n综上，方案 A 看起来更好。\n")


def m_break_command(root):
    sub(report(root), "python3 -X utf8 ", "python3 ")


def m_hide_mismatch(root):
    name = "langgraph"
    p = os.path.join(root, "bench", "cross_eval", "raw", "%s_summary.json" % name)
    d = json.loads(read(p))
    modes = d.get("modes") or {}
    if not modes:
        raise AnchorMiss("summary 里没有 modes")
    k = sorted(modes)[0]
    modes[k]["matches_golden"] = False
    write(p, json.dumps(d, ensure_ascii=False, indent=2))
    t = read(report(root))
    pat = r"^.*\b%s\b.*(?:不一致|match=False|match: False|matches_golden[^\n]*False).*$" % re.escape(k)
    if re.search(pat, t, re.M):
        raise AnchorMiss("报告已在同一行披露 %s 不一致，变异无判别力" % k)


def m_stale_golden(root):
    p = os.path.join(root, "docs", "reviews", "测评方法论_v0.1.md")
    g = golden_sha(root)
    if g not in read(p):
        raise AnchorMiss("方法论里没有黄金 sha")
    sub(p, g, FAKE_SHA)


def m_blank_untested(root):
    p = report(root)
    t = read(p)
    i = t.index("## 6. 未测项与原因")
    write(p, t[:i] + "## 6. 未测项与原因\n无。\n")


def m_unlink_conclusion(root):
    p = report(root)
    t = read(p)
    i = t.index("## 0. 结论摘要")
    j = t.index("## 1. ", i)
    head, sec0, tail = t[:i], t[i:j], t[j:]
    lines = sec0.splitlines()
    for k, ln in enumerate(lines):
        if re.match(r"^\s*(?:[-*]|\d+[.)])\s+\S", ln) and re.search(r"M[1-8]", ln):
            lines[k] = re.sub(r"M[1-8]", "M0", ln)
            break
    else:
        raise AnchorMiss("结论摘要里没有带 M 引用的条目")
    write(p, head + "\n".join(lines) + tail)


def m_drop_report(root):
    os.remove(report(root))


#: 每条变异 -> 期望被打红的判据集合。必须**恰好**相等：多红 = 判据语义纠缠，少红 = 该判据空转。
#: drop_report 期望的是扇出集：报告缺失时该报告的逐报告判据一并红（fail-closed，不许静默跳过）。
MUTATIONS = {
    "reorder_sections": ({"R2"}, m_reorder_sections),
    "fake_raw_ref": ({"R4"}, m_fake_raw_ref),
    "invent_reading": ({"R5"}, m_invent_reading),
    "judge_phrase": ({"R6"}, m_judge_phrase),
    "break_command": ({"R7"}, m_break_command),
    "hide_mismatch": ({"R8"}, m_hide_mismatch),
    "stale_golden": ({"R9"}, m_stale_golden),
    "blank_untested": ({"R10"}, m_blank_untested),
    "unlink_conclusion": ({"R12"}, m_unlink_conclusion),
    "drop_report": ({"R1", "R2", "R4", "R5", "R6", "R7", "R8", "R10", "R11", "R12"}, m_drop_report),
}


def run_guard(root):
    cmd = [sys.executable, "-X", "utf8",
           os.path.join(root, "scripts", "check_reviews.py"), "--root", root, "--quiet"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    red = sorted(l.split()[1] for l in p.stdout.splitlines() if l.startswith("RED "))
    ran = [l.split()[1] for l in p.stdout.splitlines() if l.startswith("RAN ")]
    return red, (ran[0] if ran else "0"), p.returncode


def scratch_copy(root):
    d = tempfile.mkdtemp(prefix="checkreviews-")
    for rel in ("scripts", "docs", "bench"):
        src = os.path.join(root, rel)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(d, rel))
    return d


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--mutate", nargs="?", const="__all__", default=None)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    only_mut = args.mutate == "__all__"
    if args.mutate and not only_mut:
        if args.mutate not in MUTATIONS:
            print("未知变异：%s（可选：%s）" % (args.mutate, ",".join(sorted(MUTATIONS))))
            return 2
        expect, fn = MUTATIONS[args.mutate]
        d = scratch_copy(root)
        try:
            fn(d)
        except AnchorMiss as e:
            print("ANCHOR-MISS %s" % e)
            return 2
        red, ran, rc = run_guard(d)
        for i in red:
            print("RED %s" % i)
        print("RAN %s" % ran)
        print("EXPECT %s" % ",".join(sorted(expect)))
        if not args.keep:
            shutil.rmtree(d, ignore_errors=True)
        return 0 if set(red) == expect else 1

    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    if not only_mut:
        d0 = scratch_copy(root)
        red, ran, rc = run_guard(d0)
        check("A1 正向：真实交付集全绿（守卫 0 红）", red == [] and rc == 0, "红项=%s rc=%s" % (red, rc))
        shutil.rmtree(d0, ignore_errors=True)

    for mid, (expect, fn) in sorted(MUTATIONS.items()):
        d = scratch_copy(root)
        try:
            fn(d)
        except AnchorMiss as e:
            check("A-%s 变异锚点存在" % mid, False, "ANCHOR-MISS %s" % e)
            shutil.rmtree(d, ignore_errors=True)
            continue
        red, ran, rc = run_guard(d)
        check("A-%s 变异恰好打红 %s" % (mid, ",".join(sorted(expect))), set(red) == expect,
              "实际红项=%s" % red)
        shutil.rmtree(d, ignore_errors=True)

    if not only_mut:
        gp = os.path.join(root, "scripts", "check_reviews.py")
        p = subprocess.run([sys.executable, "-X", "utf8", gp, "--list"], capture_output=True, text=True)
        ids = [l for l in p.stdout.splitlines() if l.strip()]
        check("A11 判据数 >= 10 且无重复", len(ids) >= 10 and len(set(ids)) == len(ids), "判据=%d" % len(ids))

    nfail = sum(1 for _, ok, _ in results if not ok)
    if args.quiet:
        for name, ok, detail in results:
            if not ok:
                print("RED %s" % name)
        print("RAN %d" % len(results))
        return 1 if nfail else 0
    for name, ok, detail in results:
        print("%s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + detail) if detail and not ok else ""))
    print("通过 %d / 失败 %d" % (len(results) - nfail, nfail))
    return 1 if nfail else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AnchorMiss as e:
        print("ANCHOR-MISS %s" % e)
        sys.exit(2)
