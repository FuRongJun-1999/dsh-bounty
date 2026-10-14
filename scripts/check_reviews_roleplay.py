# -*- coding: utf-8 -*-
"""守卫：docs/reviews/ 下角色扮演方向报告的「可复跑 + 可指认 + 不吹」机械核对。

为什么需要本件：角色扮演测评的核心风险是「用不可判的形容词代替读数」。报告里的每个
读数行必须能在 bench/roleplay_eval/raw/ 逐字指到；没读数的项必须显式写成「未测」；
方案自己声明的 unsupported 字段必须在报告正文里被点到名。这是映射规则，不是排版细节，
故每条判据配一个定点变异自证（见 spike/guard-lab/）。

判据（每条一个稳定 id）：
  R1  交付文件齐备：SillyTavern / RisuAI / diceframe 三份方案报告 + 角色扮演测评方法论
  R2  方案报告逐字含 CONTRACT §5 的七个二级标题，且顺序一致
  R3  方法论含 ## 1. – ## 9. 九节，且五个具名标题（读数项 / 公平性规则 /
      复现步骤（第三方原样可跑） / 不适用条件 / 未测项与原因）逐字存在
  R4  报告与方法论引用的每个 raw/<文件>（须带扩展名）在 raw/ 下真实存在
  R5  围栏代码块里以 READOUT/DIFF/KPI/SHA/DETERMINISM/TIMING/CAPS/UNSUPPORTED/ERROR
      开头的行，必须能在 raw/*.txt 里逐字找到（防编造读数）
  R6  全件禁用「不可判词」表（见 BANNED，零 LLM 判官）
  R7  方案报告 §2 含可原样执行的适配器命令（python/node/npx 开头且含 adapters/）
  R8  声称与证据一致：raw/<name>_summary.json 某档 determinism.identical=false 或该档
      errors 非空时，对应报告里必须有**同一行**同时出现方案名与不一致标记
  R9  方法论**正文**（围栏外）写出 data/worldbook.json 与 data/chat.jsonl 的 sha256，
      且与实测值一致（围栏内的样例行不算：那是 raw 日志的复述，可被 R5 覆盖；
      若两者都算，只改正文的定点变异会被围栏副本掩盖 ⇒ 判据空转）
  R10 方案报告 §6 含「未测」且正文 >=40 字符
  R11 方案报告 §5 正文 >=40 字符
  R12 报告 §0 结论摘要每个列表项都带 M1–M8 引用，且至少引用 3 个不同编号
  R13 每个 bench/roleplay_eval/out/*.json 里 unsupported 的 field 必须在对应报告正文
      里出现；按 adapter 字段或文件名前缀对应方案报告，对应不上方案报告的落到方法论
      （基线读数记在方法论里，否则基线 out 的 unsupported 无人可指 ⇒ 判据空转）

用法：
  python -X utf8 scripts/check_reviews_roleplay.py               # 正向：末行「通过 N / 失败 M」
  python -X utf8 scripts/check_reviews_roleplay.py --quiet       # 只输出 RED <id> 与 RAN <n>
  python -X utf8 scripts/check_reviews_roleplay.py --root <dir>  # 指定仓库根（变异体在沙箱里跑）
  python -X utf8 scripts/check_reviews_roleplay.py --list        # 只列判据
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
    "SillyTavern_v0.1.md": "SillyTavern",
    "RisuAI_v0.1.md": "RisuAI",
    "diceframe_v0.1.md": "diceframe",
}
METHOD_REPORT = "测评方法论_角色扮演_v0.1.md"
BASELINE_ADAPTER = "baseline"

SCHEME_HEADINGS = [
    "## 0. 结论摘要",
    "## 1. 被测对象与版本",
    "## 2. 复现步骤",
    "## 3. 基线 vs 方案对照读数",
    "## 4. 读数明细",
    "## 5. 不适用条件",
    "## 6. 未测项与原因",
]
METHOD_HEADINGS = ["读数项", "公平性规则", "复现步骤（第三方原样可跑）", "不适用条件", "未测项与原因"]

#: 不可判词表（>=8 条，前六条为任务书强制项）。
BANNED = [
    "看起来更好",
    "体验更佳",
    "更优雅",
    "大概",
    "应该是",
    "感觉不错",
    "更强大",
    "明显更好",
    "效果好得多",
    "显然更优",
]

#: 读数行前缀（CONTRACT §7.2）。
READOUT_PREFIX_RE = re.compile(
    r"^(?:READOUT|DIFF|KPI|SHA|DETERMINISM|TIMING|CAPS|UNSUPPORTED|ERROR)\s")
#: raw/ 证据文件引用；要求带扩展名，避免把 raw/<name>_* 这类通配写法误判成悬空引用。
RAW_REF_RE = re.compile(r"raw/[A-Za-z0-9_.\-]+\.(?:txt|json|jsonl|sh|py|md|log)")
#: 可原样执行的适配器命令（CONTRACT §5 第 2 节）。
ADAPTER_CMD_RE = re.compile(r"^\s*(?:\$\s*)?(?:python[0-9.]*|py|node|npx)\b[^\n]*adapters/", re.M)
#: R8 的「不一致标记」：必须与方案名同行。
INCONSISTENT_RE = re.compile(
    r"(?:不一致|identical\s*[=:]\s*false|errors\s*非空|非空\s*errors)", re.I)
OUT_PROFILE_RE = re.compile(r"_P[0-9]+$")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def raw_txt_pool(raw_dir):
    """raw/*.txt 的逐字行池（R5 只认 .txt，json 不参与逐字比对）。"""
    pool = set()
    if not os.path.isdir(raw_dir):
        return pool
    for fn in sorted(os.listdir(raw_dir)):
        p = os.path.join(raw_dir, fn)
        if not os.path.isfile(p) or not fn.lower().endswith(".txt"):
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


def unsupported_fields(obj):
    """从 out/*.json 里取出 unsupported 的 field 集合（兼容 list/dict/str 三种写法）。"""
    fields = []
    u = obj.get("unsupported") if isinstance(obj, dict) else None
    if isinstance(u, list):
        for item in u:
            if isinstance(item, dict) and isinstance(item.get("field"), str):
                fields.append(item["field"])
            elif isinstance(item, str) and item:
                fields.append(item)
    elif isinstance(u, dict):
        fields.extend([k for k in u if isinstance(k, str)])
    return sorted(set(fields))


def checks(root):
    ids = ["R%d" % i for i in range(1, 14)]

    def run(r):
        reviews = os.path.join(r, "docs", "reviews")
        bench = os.path.join(r, "bench", "roleplay_eval")
        raw = os.path.join(bench, "raw")
        data = os.path.join(bench, "data")
        out = os.path.join(bench, "out")
        red, detail = set(), {}

        def mark(cid, msg):
            red.add(cid)
            detail.setdefault(cid, [])
            if msg not in detail[cid]:
                detail[cid].append(msg)

        texts = {}
        for fn in list(SCHEME_REPORTS) + [METHOD_REPORT]:
            p = os.path.join(reviews, fn)
            texts[fn] = read_text(p) if os.path.isfile(p) else None
        for fn, t in texts.items():
            if t is None:
                mark("R1", "缺 docs/reviews/%s" % fn)

        pool = raw_txt_pool(raw)
        by_key = {}
        for fn in SCHEME_REPORTS:
            by_key[fn[:-len("_v0.1.md")].lower()] = fn

        for fn in SCHEME_REPORTS:
            t = texts.get(fn)
            if t is None:
                for cid in ("R2", "R4", "R5", "R6", "R7", "R8", "R10", "R11", "R12"):
                    mark(cid, "缺 %s，无法核对" % fn)
                continue
            pos, ok = -1, True
            for h in SCHEME_HEADINGS:
                i = t.find(h)
                if i < 0 or i <= pos:
                    ok = False
                    break
                pos = i
            if not ok:
                mark("R2", "%s 缺标题或顺序不符" % fn)
            for ref in sorted(set(RAW_REF_RE.findall(t))):
                if not os.path.exists(os.path.join(raw, os.path.basename(ref))):
                    mark("R4", "%s 引用悬空 %s" % (fn, ref))
            for block in fenced_blocks(t):
                for line in block:
                    s = line.strip()
                    if s and READOUT_PREFIX_RE.match(s) and s not in pool:
                        mark("R5", "%s 读数行在 raw/*.txt 里指不到：%s" % (fn, s[:60]))
            for b in BANNED:
                if b in t:
                    mark("R6", "%s 含不可判词「%s」" % (fn, b))
            sec2 = section_body(t, "## 2. 复现步骤")
            if not sec2 or not ADAPTER_CMD_RE.search(sec2):
                mark("R7", "%s §2 无可原样执行的适配器命令" % fn)
            sec0 = section_body(t, "## 0. 结论摘要") or ""
            items = [ln for ln in sec0.splitlines() if re.match(r"^\s*(?:[-*]|\d+[.)])\s+\S", ln)]
            mids = set(re.findall(r"M[1-8]", sec0))
            if (not items or len(mids) < 3
                    or any(not re.search(r"M[1-8]", ln) for ln in items)):
                mark("R12", "%s §0 有结论项缺 M 引用或不同编号 <3" % fn)
            sec5 = section_body(t, "## 5. 不适用条件")
            if not sec5 or len(sec5.strip()) < 40:
                mark("R11", "%s §5 正文不足 40 字符" % fn)
            sec6 = section_body(t, "## 6. 未测项与原因")
            if not sec6 or "未测" not in sec6 or len(sec6.strip()) < 40:
                mark("R10", "%s §6 缺「未测」或正文不足 40 字符" % fn)
            # R8：summary 里的档位证据 vs 报告里的披露
            name = SCHEME_REPORTS[fn]
            sp = os.path.join(raw, "%s_summary.json" % name)
            if not os.path.isfile(sp):
                mark("R8", "缺 raw/%s_summary.json，无从核对" % name)
            else:
                try:
                    d = json.loads(read_text(sp))
                except ValueError:
                    mark("R8", "raw/%s_summary.json 不是合法 JSON" % name)
                    d = None
                if isinstance(d, dict):
                    det = d.get("determinism") or {}
                    profiles = d.get("profiles") or {}
                    for prof in sorted(profiles):
                        rec = profiles[prof]
                        if not isinstance(rec, dict):
                            continue
                        bad = bool(rec.get("errors"))
                        dd = rec.get("determinism")
                        if isinstance(dd, dict):
                            ident = dd.get("identical")
                        elif isinstance(det.get(prof), dict):
                            ident = det[prof].get("identical")
                        else:
                            ident = None
                        if ident is False:
                            bad = True
                        if not bad:
                            continue
                        # 同一行必须同时出现方案名与不一致标记（全篇出现「不一致」不算）
                        hit = any(name in ln and INCONSISTENT_RE.search(ln)
                                  for ln in t.splitlines())
                        if not hit:
                            mark("R8", "%s 档 %s 有证据但报告无同行披露"
                                 % (name, prof))

        mt = texts.get(METHOD_REPORT)
        if mt is None:
            for cid in ("R3", "R4", "R5", "R6", "R9"):
                mark(cid, "缺 %s，无法核对" % METHOD_REPORT)
        else:
            for i in range(1, 10):
                if not re.search(r"^## %d\. " % i, mt, re.M):
                    mark("R3", "方法论缺 ## %d. 节" % i)
            for h in METHOD_HEADINGS:
                if not any(ln.startswith("## ") and h in ln for ln in mt.splitlines()):
                    mark("R3", "方法论缺具名标题「%s」" % h)
            for ref in sorted(set(RAW_REF_RE.findall(mt))):
                if not os.path.exists(os.path.join(raw, os.path.basename(ref))):
                    mark("R4", "%s 引用悬空 %s" % (METHOD_REPORT, ref))
            for block in fenced_blocks(mt):
                for line in block:
                    s = line.strip()
                    if s and READOUT_PREFIX_RE.match(s) and s not in pool:
                        mark("R5", "%s 读数行在 raw/*.txt 里指不到：%s"
                             % (METHOD_REPORT, s[:60]))
            for b in BANNED:
                if b in mt:
                    mark("R6", "%s 含不可判词「%s」" % (METHOD_REPORT, b))
            prose = prose_only(mt)
            for rel in ("worldbook.json", "chat.jsonl"):
                dp = os.path.join(data, rel)
                if not os.path.isfile(dp):
                    mark("R9", "缺 data/%s，无从核对 sha256" % rel)
                    continue
                h = sha256_file(dp)
                if h not in prose:
                    mark("R9", "方法论正文未写出 data/%s 的 sha256=%s" % (rel, h))

        # R13：out/*.json 的 unsupported field 必须在对应报告正文里出现
        if os.path.isdir(out):
            for fn in sorted(os.listdir(out)):
                if not fn.lower().endswith(".json"):
                    continue
                p = os.path.join(out, fn)
                if not os.path.isfile(p):
                    continue
                try:
                    obj = json.loads(read_text(p))
                except ValueError:
                    mark("R13", "out/%s 不是合法 JSON" % fn)
                    continue
                if not isinstance(obj, dict):
                    continue
                adapter = str(obj.get("adapter") or "").lower()
                stem = fn[:-len(".json")]
                keys = [k for k in (adapter, OUT_PROFILE_RE.sub("", stem).lower()) if k]
                target = next((by_key[k] for k in keys if k in by_key), None)
                doc = texts.get(target) if target else mt
                label = target or METHOD_REPORT
                if doc is None:
                    mark("R13", "out/%s 的对应文档 %s 不存在" % (fn, label))
                    continue
                for f in unsupported_fields(obj):
                    if f not in doc:
                        mark("R13", "out/%s 的 unsupported field「%s」未在 %s 出现"
                             % (fn, f, label))

        return red, detail

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
    red, detail = run(args.root)
    if args.quiet:
        for i in sorted(red, key=lambda s: int(s[1:])):
            print("RED %s" % i)
        print("RAN %d" % len(ids))
        return 1 if red else 0
    print("检查根：%s" % os.path.abspath(args.root))
    for i in sorted(red, key=lambda s: int(s[1:])):
        for msg in detail.get(i, []):
            print("红项 %s：%s" % (i, msg))
    print("通过 %d / 失败 %d" % (len(ids) - len(red), len(red)))
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
