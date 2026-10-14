# -*- coding: utf-8 -*-
"""守卫：docs/reviews/ 下横向测评报告的「可复跑 + 可指认 + 不吹」机械核对。

为什么需要本件：测评报告的成立前提是「报告里的每个数字都能在原始日志里指到」，
且「没有读数的项被显式写成未测，而不是被静默算成好成绩」。这是**映射规则**，
不是排版细节，故必须可机械判定，且每条判据配一个**定点变异**自证（见 tests/test_check_reviews.py）。

判据（每条一个稳定 id）：
  R1  交付文件齐备：三家方案报告 + 测评方法论
  R2  方案报告逐字含七个必需二级标题（顺序一致）
  R3  方法论含 1-9 节 且五个具名标题逐字存在
  R4  报告/方法论里引用的每个 raw/<文件> 都真实存在
  R5  围栏代码块里的**读数行**必须能在 raw/ 原始文本里逐字找到（防编造读数）
  R6  禁用「无读数判官词」（零 LLM 判官）
      （R4/R5/R6 覆盖全部交付文档：三份方案报告 ＋ 测评方法论）
  R7  方案报告 2 节含一条可原样执行的复跑命令（python3 -X utf8 ... runner.py）
  R8  声称与证据一致：summary 里 matches_golden=false 的模式必须在报告里**同一行**披露
      「模式名 + 不一致/match=False」（全篇随便出现「不一致」不算）
  R9  黄金产物指纹：data/out_baseline.jsonl 的实际 sha256 必须出现在方法论的**正文**里
      （围栏样例行不算：那是 raw 日志的复述，可被 R5 覆盖；若两者都算，只改正文的
      定点变异会被围栏副本掩盖 ⇒ 判据空转）
  R10 方案报告 6 节写了未测项（含「未测」且正文 >=40 字符）
  R11 方案报告 5 节写了不适用条件（正文 >=40 字符）
  R12 结论逐项可指：0 节结论摘要里每个编号/项目条目都带 M1-M8 引用，且至少引用 3 个不同读数项

用法：
  python -X utf8 scripts/check_reviews.py                 # 正向：末行「通过 N / 失败 M」
  python -X utf8 scripts/check_reviews.py --quiet         # 只输出 RED <id>（供变异自证解析）
  python -X utf8 scripts/check_reviews.py --root <dir>    # 指定仓库根（变异体在沙箱里跑）
  python -X utf8 scripts/check_reviews.py --list          # 只列判据
退出码：0 = 全绿；1 = 有红项。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)
FENCE = chr(96) * 3

SCHEME_REPORTS = {
    "LangGraph_v0.1.md": "langgraph",
    "LlamaIndex-Workflows_v0.1.md": "llamaindex",
    "txtai-Workflow_v0.1.md": "txtai",
}
METHOD_REPORT = "测评方法论_v0.1.md"

SCHEME_HEADINGS = [
    "## 0. 结论摘要",
    "## 1. 被测对象与版本",
    "## 2. 复现步骤",
    "## 3. 基线 vs 方案对照读数",
    "## 4. 读数明细",
    "## 5. 不适用条件",
    "## 6. 未测项与原因",
]
METHOD_HEADINGS = [
    "## 4. 读数项",
    "## 5. 公平性规则",
    "## 6. 复现步骤（第三方原样可跑）",
    "## 8. 不适用条件",
    "## 9. 未测项与原因",
]
BANNED = ["看起来更好", "体验更佳", "更优雅", "更强大", "大概是", "应该是", "感觉不错"]

#: 读数行的判据：出现在原始日志里、且**必须逐字可指**的行形态。
READING_RE = re.compile(
    r"(RUN mode=|\bSHA [0-9a-f]{64}|\bTRACE |\bATTEMPTS |\bCAPS |REEXECUTED|FIRST_ERROR"
    r"|ERROR_TEXT|\bTIMING |SUMMARY_WRITTEN|[0-9a-f]{64})")
#: raw/ 证据文件引用（要求带扩展名，避免把 raw/<name>_* 这类通配写法误判成悬空引用）。
RAW_REF_RE = re.compile(r"raw/[A-Za-z0-9_.\-]+\.(?:txt|json|jsonl|sh|py|md|log)")
#: 围栏里允许出现、不必逐字可指的行（命令 / 环境 / 注释 / 表头）。
CMD_PREFIX = ("python3", "pip ", "cd ", "export ", "PYTHONPATH", "$ ", "#", "|", "---")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def raw_pool(raw_dir):
    pool = set()
    if not os.path.isdir(raw_dir):
        return pool
    for fn in sorted(os.listdir(raw_dir)):
        p = os.path.join(raw_dir, fn)
        if not os.path.isfile(p):
            continue
        for line in read_text(p).splitlines():
            s = line.strip()
            if s:
                pool.add(s)
    return pool


def fenced_blocks(text):
    blocks, cur, inside = [], [], False
    for line in text.splitlines():
        if line.strip().startswith(FENCE):
            if inside:
                blocks.append(cur)
                cur, inside = [], False
            else:
                inside = True
            continue
        if inside:
            cur.append(line)
    if cur:
        blocks.append(cur)
    return blocks


def prose_only(text):
    """去掉围栏代码块后的正文。

    R9 用它在**正文**里找黄金 sha：围栏里的样例行是 raw 日志的复述（可被 R5 覆盖），
    若把两者都算作「写明了黄金 sha」，那么只改正文一处的定点变异会被围栏里的副本掩盖
    ⇒ 判据空转（实测踩过）。
    """
    out, inside = [], False
    for line in text.splitlines():
        if line.strip().startswith(FENCE):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    return "\n".join(out)


def section_body(text, heading):
    idx = text.find(heading)
    if idx < 0:
        return None
    rest = text[idx + len(heading):]
    m = re.search(r"^## ", rest, re.M)
    return rest[:m.start()] if m else rest


def checks(root):
    ids = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"]

    def run(r):
        reviews = os.path.join(r, "docs", "reviews")
        raw = os.path.join(r, "bench", "cross_eval", "raw")
        data = os.path.join(r, "bench", "cross_eval", "data")
        red = set()
        texts = {}
        for fn in list(SCHEME_REPORTS) + [METHOD_REPORT]:
            p = os.path.join(reviews, fn)
            texts[fn] = read_text(p) if os.path.isfile(p) else None

        for fn, t in texts.items():
            if t is None:
                red.add("R1")

        pool = raw_pool(raw)
        for fn, name in SCHEME_REPORTS.items():
            t = texts.get(fn)
            if t is None:
                red.update(["R2", "R4", "R5", "R6", "R7", "R10", "R11", "R12"])
                continue
            pos, ok = -1, True
            for h in SCHEME_HEADINGS:
                i = t.find(h)
                if i < 0 or i <= pos:
                    ok = False
                    break
                pos = i
            if not ok:
                red.add("R2")
            for ref in set(RAW_REF_RE.findall(t)):
                if not os.path.exists(os.path.join(raw, os.path.basename(ref))):
                    red.add("R4")
            for block in fenced_blocks(t):
                for line in block:
                    s = line.strip()
                    if not s or s.startswith(CMD_PREFIX):
                        continue
                    if READING_RE.search(s) and s not in pool:
                        red.add("R5")
            if any(b in t for b in BANNED):
                red.add("R6")
            sec2 = section_body(t, "## 2. 复现步骤")
            if not sec2 or not re.search(r"^python3 -X utf8 .*runner\.py", sec2, re.M):
                red.add("R7")
            sec5 = section_body(t, "## 5. 不适用条件")
            if not sec5 or len(sec5.strip()) < 40:
                red.add("R11")
            sec6 = section_body(t, "## 6. 未测项与原因")
            if not sec6 or "未测" not in sec6 or len(sec6.strip()) < 40:
                red.add("R10")
            sec0 = section_body(t, "## 0. 结论摘要") or ""
            items = [ln for ln in sec0.splitlines() if re.match(r"^\s*(?:[-*]|\d+[.)])\s+\S", ln)]
            mids = set(re.findall(r"M[1-8]", sec0))
            if (not items or len(mids) < 3
                    or any(not re.search(r"M[1-8]", ln) for ln in items)):
                red.add("R12")

        mt = texts.get(METHOD_REPORT)
        if mt is None:
            red.update(["R3", "R9"])
        else:
            for i in range(1, 10):
                if not re.search(r"^## %d\. " % i, mt, re.M):
                    red.add("R3")
            for h in METHOD_HEADINGS:
                if h not in mt:
                    red.add("R3")
            # 方法论里的基线读数同样必须可指认（R4/R5/R6 覆盖全部交付文档）
            for ref in set(RAW_REF_RE.findall(mt)):
                if not os.path.exists(os.path.join(raw, os.path.basename(ref))):
                    red.add("R4")
            for block in fenced_blocks(mt):
                for line in block:
                    s = line.strip()
                    if not s or s.startswith(CMD_PREFIX):
                        continue
                    if READING_RE.search(s) and s not in pool:
                        red.add("R5")
            if any(b in mt for b in BANNED):
                red.add("R6")
            gp = os.path.join(data, "out_baseline.jsonl")
            if not os.path.isfile(gp) or sha256_file(gp) not in prose_only(mt):
                red.add("R9")

        for fn, name in SCHEME_REPORTS.items():
            t = texts.get(fn)
            sp = os.path.join(raw, "%s_summary.json" % name)
            if t is None or not os.path.isfile(sp):
                red.add("R8")
                continue
            try:
                d = json.loads(read_text(sp))
            except ValueError:
                red.add("R8")
                continue
            modes = d.get("modes") or {}
            # 逐模式判据：某个模式在 summary 里 matches_golden=false 时，报告里必须有
            # **同一行同时出现该模式名与不一致标记**的披露（全篇出现「不一致」不算，
            # 否则「口径不一致」这类无关句子会让判据空转）。
            for mode, rec in sorted(modes.items()):
                if not isinstance(rec, dict) or not rec.get("sha256"):
                    continue
                if rec.get("matches_golden") is False:
                    pat = r"^.*\b%s\b.*(?:不一致|match=False|match: False|matches_golden[^\n]*False).*$" % re.escape(mode)
                    if not re.search(pat, t, re.M):
                        red.add("R8")
        return red

    return ids, run


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    ids, run = checks(args.root)
    if args.list:
        for i in ids:
            print(i)
        return 0
    red = run(args.root)
    if args.quiet:
        for i in sorted(red):
            print("RED %s" % i)
        print("RAN %d" % len(ids))
        return 1 if red else 0
    print("检查根：%s" % os.path.abspath(args.root))
    if red:
        print("红项：%s" % sorted(red))
    print("通过 %d / 失败 %d" % (len(ids) - len(red), len(red)))
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
