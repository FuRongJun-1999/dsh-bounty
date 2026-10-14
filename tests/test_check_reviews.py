# -*- coding: utf-8 -*-
"""tests/test_check_reviews.py —— 守卫 scripts/check_reviews.py 的判别力自证。

做什么：把 docs/reviews/ 的真实交付集交给守卫跑一遍（正向必须全绿），
然后对**沙箱副本**逐个施加定点变异，断言**恰好**打红预期的那一条判据
（多红 = 判据语义纠缠；少红 = 该判据空转，等于没测）。

覆盖面：R1–R14 **每条判据至少被一条定点变异打红**（R1/R3/R9 由 drop_method 与
drop_report 扇出覆盖，其余各有一条专属变异；改动一条判据的覆盖即 A11c 转红）。结构类变异
（标题重复/假头）另断言 `--quiet` 的 `NOTE` 点名行存在——「红了」与「红得说得清」是两件事。

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
METHOD = "测评方法论_v0.1.md"
FAKE_SHA = "ab" * 32

#: 守卫判据注册表的**逐字**副本：A11 用它校验 `--list` 与字面量逐字一致（防注册表被悄悄砍条）。
CRITERIA_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12", "R13", "R14"]
#: 方法论文件名（R3/R4/R5/R6 的方法论侧变异都要改它）。
METHOD_FILE = "测评方法论_v0.1.md"

H0 = "## 0. 结论摘要"
H2 = "## 2. 复现步骤"
H5 = "## 5. 不适用条件"
H6 = "## 6. 未测项与原因"

#: 结构类变异的填充段：≥40 字、含「未测」、不含判官词、不含 raw/<文件>.<扩展名> 引用。
FILL6 = ("本节为占位说明：未测项已在各引擎报告的第 6 节与原始读数里披露，"
         "此处不再重复列出，详细原因与边界见对应原始文件。")
FILL5 = ("本节为占位说明：上述不适用条件只覆盖本地单机负载，不涉及网络、凭据、厂商托管服务"
         "与分布式持久化后端，跨进程恢复也不在本轮范围内。")
FILL0 = "本节为占位说明：结论摘要的逐项引用与读数编号已在正文给出，此处不再重复列出。"
CMD2 = ("python3 -X utf8 bench/cross_eval/harness/runner.py "
        "--impl bench/cross_eval/systems/langgraph_impl.py --name langgraph "
        "--modes normal,resume,retry,sequential,parallel")
FILL2 = ("本节为占位说明：复跑命令与依赖安装在下文 §2.3 逐字给出，可直接照抄执行，"
         "不需要任何 LLM/API 凭据。\n" + CMD2)


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


def method_path(root):
    return os.path.join(root, "docs", "reviews", METHOD)


# ---------------------------------------------------------------- 变异件

def m_reorder_sections(root):
    t = read(report(root))
    i5 = t.index(H5)
    i6 = t.index(H6)
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


def m_hide_sha256(root):
    """R8 fail-closed 定点变异：把某个模式记录的 64 位指纹**删掉**（旧版 `continue` 静默放行）。

    唯一放行通道是报告里同一行声明该模式「未产出/无指纹/未落盘」；先断言该通道
    在真实报告里**不成立**，否则变异无判别力（fail-closed 的锚点自检）。
    """
    name = "langgraph"
    p = os.path.join(root, "bench", "cross_eval", "raw", "%s_summary.json" % name)
    d = json.loads(read(p))
    modes = d.get("modes") or {}
    if not modes:
        raise AnchorMiss("summary 里没有 modes")
    k = sorted(modes)[0]
    if "sha256" not in modes[k]:
        raise AnchorMiss("模式 %s 本来就没有 sha256 字段" % k)
    del modes[k]["sha256"]
    write(p, json.dumps(d, ensure_ascii=False, indent=2))
    t = read(report(root))
    pat = r"^.*\b%s\b.*(?:未产出|无指纹|未落盘|未生成|no\s+sha256).*$" % re.escape(k)
    if re.search(pat, t, re.M):
        raise AnchorMiss("报告已在同一行声明 %s 无指纹，变异无判别力" % k)


def m_stale_golden(root):
    p = method_path(root)
    g = golden_sha(root)
    if g not in read(p):
        raise AnchorMiss("方法论里没有黄金 sha")
    sub(p, g, FAKE_SHA)


def m_blank_untested(root):
    p = report(root)
    t = read(p)
    i = t.index(H6)
    write(p, t[:i] + H6 + "\n无。\n")


def m_unlink_conclusion(root):
    p = report(root)
    t = read(p)
    i = t.index(H0)
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


def m_drop_method(root):
    os.remove(method_path(root))


def m_cross_engine_reading(root):
    """把**别的引擎**（baseline）独有的读数行贴进 txtai 报告的围栏 —— 文件归属绕过面。

    改前 raw_pool 把 raw/ 下所有文件的非空行并成一个集合 ⇒ 贴条全绿；改后该行不在 txtai 的
    证据桶里，且围栏上方没有点名出处 ⇒ 必须恰好打红 R5。
    """
    p = report(root, 2)
    raw = os.path.join(root, "bench", "cross_eval", "raw")
    own = set()
    for fn in sorted(os.listdir(raw)):
        if fn.startswith("txtai_") and fn.endswith((".txt", ".json", ".jsonl")):
            own |= {l.strip() for l in read(os.path.join(raw, fn)).splitlines() if l.strip()}
    foreign = None
    for fn in sorted(os.listdir(raw)):
        if not (fn.startswith("baseline_") and fn.endswith(".txt")):
            continue
        for line in read(os.path.join(raw, fn)).splitlines():
            s = line.strip()
            if s.startswith("TRACE ") and s not in own:
                foreign = s
                break
        if foreign:
            break
    if foreign is None:
        raise AnchorMiss("找不到「baseline 有、txtai 没有」的 TRACE 行")
    write(p, read(p) + "\n" + FENCE + "\n" + foreign + "\n" + FENCE + "\n")


def m_hash_prefix_reading(root):
    """伪造读数行加 `# ` 前缀 —— CMD_PREFIX 裸 `#` 的整类免检面（改后必须恰好打红 R5）。"""
    p = report(root)
    line = "# SHA %s golden=%s match=True lines=40" % (FAKE_SHA, golden_sha(root))
    write(p, read(p) + "\n" + FENCE + "\n" + line + "\n" + FENCE + "\n")


def m_prose_invent_reading(root):
    """伪造读数行写在**正文**（围栏之外）—— R5 只扫围栏的绕过面（改后必须恰好打红 R14）。"""
    p = report(root)
    line = "SHA %s golden=%s match=True lines=40" % (FAKE_SHA, golden_sha(root))
    write(p, read(p) + "\n" + line + "\n")


def m_invent_citation(root):
    """R13 定点变异：在正文里声称某读数出自某 raw 文件，而该文件里并没有这个 token。

    用 `AB_RATIO`（真实存在的读数名，但它落在 raw/langgraph_timing_ab.txt，不在 runner.txt），
    且它不在本报告的「未落盘」豁免集里 ⇒ 必须恰好打红 R13。
    """
    p = report(root)
    t = read(p)
    i = t.index(H5)
    add = "\n补充证据：`AB_RATIO` 见 `raw/langgraph_runner.txt`。\n"
    write(p, t[:i] + add + t[i:])


def _section_span(t, heading):
    """与**旧实现**同口径的切段（只用来定位「真节」的起止，供变异构造）。"""
    i = t.index(heading)
    m = re.search(r"^## ", t[i + len(heading):], re.M)
    j = i + len(heading) + m.start() if m else len(t)
    return i, j


def _inject_before(t, heading, filler, fake_heading=None):
    i = t.index(heading)
    fh = fake_heading if fake_heading is not None else heading
    return t[:i] + fh + "\n" + filler + "\n\n" + t[i:]


def m_fake_section6(root):
    """P1-05 的原始缺陷形态：假 §6 头 ＋ ≥40 字含「未测」填充 ＋ 真 §6 清空「无。」。

    改前 section_body() 取 text.find() 首次出现 ⇒ R10 切到假头后面的填充段，真未测节无人看。
    改后 §6 在正文区出现 2 次 ⇒ 判红并点名「重复」。§5 的「证据未落盘」声明不受影响
    （假头埋在本节尾部，§5 正文一字未动）⇒ 恰好 R10，不牵连 R13。
    """
    p = report(root)
    t = read(p)
    i, j = _section_span(t, H6)
    t = t[:i] + H6 + "\n无。\n\n" + t[j:]
    write(p, _inject_before(t, H6, FILL6))


def m_dup_section5(root):
    """标题重复：§5 头出现 2 次（真 §5 内容与「证据未落盘」声明完好）⇒ 恰好 R11。

    为什么不用「把 §5 清空」：本报告的 §5 尾部载有**证据未落盘如实声明**，清空它会连带
    打红 R13（那是第二个真缺陷，不是判据空转）。重复标题是**只打 R11**的最小变异。
    """
    p = report(root)
    write(p, _inject_before(read(p), H5, FILL5))


def m_dup_section2(root):
    p = report(root)
    write(p, _inject_before(read(p), H2, FILL2))


def m_dup_section0(root):
    p = report(root)
    write(p, _inject_before(read(p), "## 1. 被测对象与版本", FILL0, fake_heading=H0))


def m_break_method_section(root):
    """方法论 §4 标题被改写 ⇒ R3 红（九节齐备里少一节）。"""
    sub(method_path(root), "## 4. 读数项", "## 4. 读数")


# ---------------------------------------------------------------- #372 补齐的八条变异
# 原 10 条变异只覆盖 11 条判据：R3 零覆盖；R2/R11/R12 各自只测一种子句；R4/R5/R6 只在
# LangGraph 一份报告上注入（方法论侧零覆盖）；R8 只被 sorted(modes)[0]=normal 证明（非首模式零覆盖）。
# 这一组把「每条判据都被至少一条变异的期望集覆盖」补成硬约束（见 A11c）。

def method_report(root):
    return os.path.join(root, "docs", "reviews", METHOD_FILE)


def append_to_method(root, text):
    """往方法论末尾追加文本；围栏行数为奇数时拒绝（否则追加内容会落进围栏内）。"""
    p = method_report(root)
    t = read(p)
    if sum(1 for ln in t.splitlines() if ln.strip().startswith(FENCE)) % 2:
        raise AnchorMiss("方法论围栏行数为奇数，追加会落进围栏内")
    write(p, t + text)


def m_drop_method_section(root):
    """R3 反面证明：删掉《测评方法论》的 `## 7. ` 一节（九节齐备缺一）。"""
    p = method_report(root)
    t = read(p)
    if len(re.findall(r"^## 7\. ", t, re.M)) != 1:
        raise AnchorMiss("方法论里 `## 7. ` 锚点缺失或不唯一")
    i7 = t.index("## 7. ")
    i8 = t.index("## 8. ", i7)
    write(p, t[:i7] + t[i8:])


def m_blank_section5(root):
    """R11 反面证明：方案报告 5 节只留标题、正文掏空（不足 40 字符）。

    本报告的「证据未落盘清单」在 §4 末尾（见 CHANGES.md 的合并判断），故清空 §5 不会连带
    打红 R13——这正是把该清单与结论性章节解耦的目的。
    """
    p = report(root)
    t = read(p)
    i = t.index("## 5. 不适用条件")
    j = t.index("## 6. ", i)
    write(p, t[:i] + "## 5. 不适用条件\n无。\n" + t[j:])


def m_method_fake_raw_ref(root):
    """R4 反面证明（方法论侧）：方法论里引用一个不存在的 raw/<文件>。"""
    append_to_method(root, "\n见 raw/method_missing_zzz.txt\n")


def m_method_invent_reading(root):
    """R5 反面证明（方法论侧）：方法论围栏里塞一行原始日志里没有的读数。"""
    line = "SHA %s golden=%s match=True lines=41" % (FAKE_SHA, golden_sha(root))
    append_to_method(root, "\n" + FENCE + "\n" + line + "\n" + FENCE + "\n")


def m_method_judge_phrase(root):
    """R6 反面证明（方法论侧）：方法论正文里出现零读数判官词。"""
    append_to_method(root, "\n综上，方案 A 看起来更好。\n")


def m_drop_scheme_heading(root):
    """R2「齐备」子句反面证明：删掉方案报告一个必需二级标题（顺序没坏，齐备坏了）。"""
    p = report(root)
    t = read(p)
    h = "## 4. 读数明细\n"
    if t.count(h) != 1:
        raise AnchorMiss("报告里 %r 出现 %d 次，锚点不唯一" % (h.strip(), t.count(h)))
    write(p, t.replace(h, "", 1))


def m_conclusion_single_ref(root):
    """R12「至少 3 个不同读数项」子句反面证明：0 节条目仍在，但全部只引 M1。"""
    p = report(root)
    t = read(p)
    i = t.index(H0)
    j = t.index("## 1. ", i)
    sec0 = t[i:j]
    if len(set(re.findall(r"M[1-8]", sec0))) < 3:
        raise AnchorMiss("结论摘要原本就不足 3 个不同读数项，变异无判别力")
    write(p, t[:i] + re.sub(r"M[2-8]", "M1", sec0) + t[j:])


def m_hide_mismatch_nonfirst(root):
    """R8 非首模式反面证明：把 summary 里 sorted(modes)[1] 翻成 false 且报告不披露。"""
    name = "langgraph"
    p = os.path.join(root, "bench", "cross_eval", "raw", "%s_summary.json" % name)
    d = json.loads(read(p))
    modes = d.get("modes") or {}
    if len(sorted(modes)) < 2:
        raise AnchorMiss("summary 里不足两个模式，无法构造非首模式变异")
    k = sorted(modes)[1]
    modes[k]["matches_golden"] = False
    write(p, json.dumps(d, ensure_ascii=False, indent=2))
    t = read(report(root))
    pat = r"^.*\b%s\b.*(?:不一致|match=False|match: False|matches_golden[^\n]*False).*$" % re.escape(k)
    if re.search(pat, t, re.M):
        raise AnchorMiss("报告已在同一行披露 %s 不一致，变异无判别力" % k)


#: 每条变异 -> 期望被打红的判据集合。必须**恰好**相等：多红 = 判据语义纠缠，少红 = 该判据空转。
#: drop_report / drop_method 期望的是扇出集：文件缺失时该文件的逐文件判据一并红
#: （fail-closed，不许静默跳过）。
#: drop_method 为什么含 R9：黄金 sha 只认方法论的**正文**，文件没了 ⇒ R9 无从成立。
MUTATIONS = {
    "reorder_sections": ({"R2"}, m_reorder_sections),
    "fake_raw_ref": ({"R4"}, m_fake_raw_ref),
    "invent_reading": ({"R5"}, m_invent_reading),
    "cross_engine_reading": ({"R5"}, m_cross_engine_reading),
    "hash_prefix_reading": ({"R5"}, m_hash_prefix_reading),
    "judge_phrase": ({"R6"}, m_judge_phrase),
    "break_command": ({"R7"}, m_break_command),
    "dup_section2": ({"R7"}, m_dup_section2),
    "hide_mismatch": ({"R8"}, m_hide_mismatch),
    "hide_sha256": ({"R8"}, m_hide_sha256),
    "stale_golden": ({"R9"}, m_stale_golden),
    "blank_untested": ({"R10"}, m_blank_untested),
    "fake_section6": ({"R10"}, m_fake_section6),
    "dup_section5": ({"R11"}, m_dup_section5),
    "unlink_conclusion": ({"R12"}, m_unlink_conclusion),
    "dup_section0": ({"R12"}, m_dup_section0),
    "invent_citation": ({"R13"}, m_invent_citation),
    "prose_invent_reading": ({"R14"}, m_prose_invent_reading),
    "break_method_section": ({"R3"}, m_break_method_section),
    "drop_method": ({"R1", "R3", "R9"}, m_drop_method),
    "drop_report": ({"R1", "R2", "R4", "R5", "R6", "R7", "R8", "R10", "R11", "R12", "R13", "R14"},
                    m_drop_report),
    # —— #372 补齐的八条（原 10 条只覆盖 11 条判据、R3 零覆盖；方法论侧 R4/R5/R6 零覆盖）——
    "drop_method_section": ({"R3"}, m_drop_method_section),
    "blank_section5": ({"R11"}, m_blank_section5),
    "method_fake_raw_ref": ({"R4"}, m_method_fake_raw_ref),
    "method_invent_reading": ({"R5"}, m_method_invent_reading),
    "method_judge_phrase": ({"R6"}, m_method_judge_phrase),
    "drop_scheme_heading": ({"R2"}, m_drop_scheme_heading),
    "conclusion_single_ref": ({"R12"}, m_conclusion_single_ref),
    "hide_mismatch_nonfirst": ({"R8"}, m_hide_mismatch_nonfirst),
}

#: 改后 `--quiet` 必须为结构类缺陷打出的 NOTE 点名（标题重复）。「红了」与「红得说得清」
#: 分开断言：NOTE 缺失只说明诊断退化，NOTE 存在才是点名能力。
NOTE_CASES = {
    "dup_section5": ("R11", "重复"),
    "dup_section0": ("R12", "重复"),
    "fake_section6": ("R10", "重复"),
}


def run_guard(root):
    cmd = [sys.executable, "-X", "utf8",
           os.path.join(root, "scripts", "check_reviews.py"), "--root", root, "--quiet"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    red = sorted(l.split()[1] for l in (p.stdout or "").splitlines() if l.startswith("RED "))
    ran = [l.split()[1] for l in (p.stdout or "").splitlines() if l.startswith("RAN ")]
    notes = [l for l in (p.stdout or "").splitlines() if l.startswith("NOTE ")]
    return red, (ran[0] if ran else "0"), p.returncode, notes


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
        red, ran, rc, notes = run_guard(d)
        for i in red:
            print("RED %s" % i)
        for n in notes:
            print("%s" % n)
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
        red, ran, rc, _notes = run_guard(d0)
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
        red, ran, rc, notes = run_guard(d)
        check("A-%s 变异恰好打红 %s" % (mid, ",".join(sorted(expect))), set(red) == expect,
              "实际红项=%s" % red)
        shutil.rmtree(d, ignore_errors=True)

    # 点名面：结构类缺陷除「红」之外还必须给出可读的 NOTE（否则只能靠猜）
    for mid, (rid, word) in sorted(NOTE_CASES.items()):
        d = scratch_copy(root)
        fn = MUTATIONS[mid][1]
        try:
            fn(d)
            _red, _ran, _rc, notes = run_guard(d)
        except AnchorMiss as e:
            check("A-note-%s 结构缺陷点名" % mid, False, "ANCHOR-MISS %s" % e)
            shutil.rmtree(d, ignore_errors=True)
            continue
        hit = [n for n in notes if n.startswith("NOTE %s " % rid) and word in n]
        check("A-note-%s 结构缺陷点名 %s（含「%s」）" % (mid, rid, word), bool(hit),
              "NOTE 行=%s" % notes)
        shutil.rmtree(d, ignore_errors=True)

    if not only_mut:
        gp = os.path.join(root, "scripts", "check_reviews.py")
        p = subprocess.run([sys.executable, "-X", "utf8", gp, "--list"], capture_output=True, text=True)
        ids = [l for l in p.stdout.splitlines() if l.strip()]
        covered = set()
        for _expect, _fn in MUTATIONS.values():
            covered |= set(_expect)
        # A11 收紧（#372）：原先只断言 `len(ids) >= 10`，于是把判据注册表从 12 条砍到 10 条、
        # 或删掉一整条判据的反面证明，套件仍全绿。现在三条一起断：
        #   ① 条数与模块常量 CRITERIA_IDS 逐字对齐且无重复；
        #   ② `--list` 与 CRITERIA_IDS **逐字一致**（顺序也算）；
        #   ③ 每条判据至少被一条变异的期望集覆盖（覆盖矩阵缺一格 = 缺一条反面证明）。
        check("A11 判据数 == %d 且无重复" % len(CRITERIA_IDS),
              len(ids) == len(CRITERIA_IDS) and len(set(ids)) == len(ids), "判据=%d" % len(ids))
        check("A11b --list 与判据字面量逐字一致", ids == list(CRITERIA_IDS),
              "--list=%s 字面量=%s" % (ids, list(CRITERIA_IDS)))
        check("A11c 每条判据至少被一条变异的期望集覆盖", set(CRITERIA_IDS) <= covered,
              "未覆盖=%s" % sorted(set(CRITERIA_IDS) - covered))

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
