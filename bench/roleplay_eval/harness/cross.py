#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨方案对照器（角色扮演横评 · 世界书触发＋上下文预算）。

读 out/{baseline,diceframe,risuai,sillytavern}_P*.json，产出两份 raw/ 读数文件：

| 产物 | 内容 |
|---|---|
| raw/cross_matrix.txt | 逐 (profile, turn) 的 CROSS 行；再一组两两 CROSSPAIR 行（baseline↔三家、三家彼此） |
| raw/cross_baseline_diff.txt | 三家各自 vs baseline 的 DIFF 行 |

用法：
  python -X utf8 bench/roleplay_eval/harness/cross.py
  python -X utf8 bench/roleplay_eval/harness/cross.py --out-dir <out> --raw-dir <raw>
  python -X utf8 bench/roleplay_eval/harness/cross.py --check     # 只算不落盘

口径：
  - 只用 Python 标准库；运行期零网络、零凭据、不调用任何 LLM。
  - 集合差、DIFF 行字段含义、uid 升序、空集合写 `-`，与 harness/metrics.py 的
    diff_sets / fmt_uids 一致（本文件自带实现，不 import 同目录模块，可单独拷走运行）。
  - 幂等：同一输入重复运行，产物逐字节相同；内容未变则不重写文件，不写时间戳。
  - 缺方案或缺档：CROSS 行只列真正有 out/<name>_<P>.json 的方案，缺席名单写在文件头注释里。
  - raw/<name>_baseline_diff.txt 已存在时按行汇总并逐行核对；不一致的行改由 out/ 现算，
    并在 stdout 用 DIFFCHECK ... match=false 点名。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent                      # bench/roleplay_eval

SCHEMES = ("diceframe", "risuai", "sillytavern")
ADAPTER_ORDER = ("baseline",) + SCHEMES
PAIRS = (
    ("baseline", "diceframe"),
    ("baseline", "risuai"),
    ("baseline", "sillytavern"),
    ("diceframe", "risuai"),
    ("diceframe", "sillytavern"),
    ("risuai", "sillytavern"),
)
ONLY_A_ONLY_B_RE = re.compile(
    r"^DIFF (\S+) (\S+) (\S+) turn=(\d+) only_a=(\S+) only_b=(\S+) same=(\d+)$")


# ---------- 量尺（与 harness/metrics.py 同口径） ----------

def fmt_uids(uids):
    """uid 升序连接；空集合写 -（CONTRACT §7.2）。"""
    xs = sorted(int(u) for u in uids)
    return ",".join(str(u) for u in xs) if xs else "-"


def diff_sets(a, b):
    """返回 (only_a, only_b, same)：对称差两侧 ＋ 交集大小。"""
    sa, sb = set(a), set(b)
    return sorted(sa - sb), sorted(sb - sa), len(sa & sb)


def diff_line(a, b, profile, turn, set_a, set_b):
    only_a, only_b, same = diff_sets(set_a, set_b)
    return "DIFF %s %s %s turn=%d only_a=%s only_b=%s same=%d" % (
        a, b, profile, turn, fmt_uids(only_a), fmt_uids(only_b), same)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_if_changed(path, text):
    """内容相同就不动文件（幂等）；一致用 LF，UTF-8。返回 (写入?, sha256)。"""
    digest = sha256_text(text)
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False, digest
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True, digest


# ---------- 输入 ----------

def load_turns(path):
    """读 out/<name>_<P>.json → {turn: {"active": [uid], "order": [uid]}}；读不到返回 {}。"""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    turns = {}
    for t in doc.get("turns") or []:
        if not isinstance(t, dict):
            continue
        try:
            turns[int(t["turn"])] = {
                "active": sorted({int(u) for u in (t.get("active_uids") or [])}),
                "order": [int(u) for u in (t.get("inject_order") or [])],
            }
        except (KeyError, TypeError, ValueError):
            continue
    return turns


def discover(out_dir):
    """→ {name: {profile: {turn: {...}}}}；只收有 turns 的文件。"""
    data = {}
    for name in ADAPTER_ORDER:
        per = {}
        for path in sorted(out_dir.glob("%s_P*.json" % name)):
            profile = path.stem.rsplit("_", 1)[-1]
            turns = load_turns(path)
            if turns:
                per[profile] = turns
        if per:
            data[name] = per
    return data


def profiles_of(data):
    return sorted({p for per in data.values() for p in per})


def turns_of(data):
    return sorted({t for per in data.values() for turns in per.values() for t in turns})


def active_at(data, name, profile, turn):
    """该方案在该 (档, 轮) 的激活集；无此读数返回 None。"""
    per = data.get(name)
    if not per or profile not in per:
        return None
    return per[profile].get(turn, {}).get("active")


def existing_diff_lines(raw_dir, name):
    """读 raw/<name>_baseline_diff.txt 里 a=name、b=baseline 的 DIFF 行 → {(profile,turn): line}。"""
    path = raw_dir / ("%s_baseline_diff.txt" % name)
    out = {}
    if not path.is_file():
        return out, None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out, None
    for line in text.replace("\r\n", "\n").split("\n"):
        m = ONLY_A_ONLY_B_RE.match(line.strip())
        if not m:
            continue
        a, b, profile, turn = m.group(1), m.group(2), m.group(3), int(m.group(4))
        if a == name and b == "baseline":
            out[(profile, turn)] = line.strip()
    return out, path


# ---------- 产物 ----------

def build_matrix(data, profiles, turns):
    lines = []
    cross = 0
    for profile in profiles:
        for turn in turns:
            parts = []
            for name in ADAPTER_ORDER:
                if name not in data:
                    continue
                act = active_at(data, name, profile, turn)
                if act is None:
                    continue
                parts.append("%s=%s" % (name, fmt_uids(act)))
            if not parts:
                continue
            lines.append("CROSS %s turn=%d %s" % (profile, turn, " ".join(parts)))
            cross += 1
    pair_rows = []
    for a, b in PAIRS:
        if a not in data or b not in data:
            continue
        for profile in profiles:
            for turn in turns:
                sa = active_at(data, a, profile, turn)
                sb = active_at(data, b, profile, turn)
                if sa is None or sb is None:
                    continue
                only_a, only_b, same = diff_sets(sa, sb)
                pair_rows.append("CROSSPAIR %s %s %s turn=%d only_a=%s only_b=%s same=%d"
                                 % (a, b, profile, turn, fmt_uids(only_a),
                                    fmt_uids(only_b), same))
    present = [n for n in ADAPTER_ORDER if n in data]
    missing = [n for n in ADAPTER_ORDER if n not in data]
    head = [
        "# cross.py 跨方案对照矩阵（角色扮演横评 · 世界书触发＋上下文预算）",
        "# 输入 out/<name>_<P>.json 的 turns[].active_uids（方案名按基线与三家的固定顺序）",
        "# 行语法 CROSS <profile> turn=<k> <name>=<uid,uid> …；uid 升序；空集合写 -；只列有该档读数的方案",
        "# 行语法 CROSSPAIR <a> <b> <profile> turn=<k> only_a=<uids> only_b=<uids> same=<n>；空集合写 -",
        "# only_a=a 侧独有 only_b=b 侧独有 same=交集大小",
        "# 在位方案：%s" % (",".join(present) if present else "-"),
        "# 缺席方案：%s" % (",".join(missing) if missing else "-"),
        "",
        "# ---- CROSS：逐 (profile, turn) 四家激活集 ----",
    ]
    body = [""] + ["# ---- CROSSPAIR：两两对照（baseline↔三家、三家彼此） ----"] + pair_rows
    text = "\n".join(head + lines + body) + "\n"
    return text, cross, len(pair_rows), missing


def build_baseline_diff(data, raw_dir):
    scheme_names = [n for n in SCHEMES if n in data]
    lines = []
    checks = []
    for name in scheme_names:
        existing, path = existing_diff_lines(raw_dir, name)
        computed = {}
        for profile in profiles_of(data):
            for turn in turns_of(data):
                sa = active_at(data, name, profile, turn)
                sb = active_at(data, "baseline", profile, turn)
                if sa is None or sb is None:
                    continue
                computed[(profile, turn)] = diff_line(name, "baseline", profile, turn, sa, sb)
        if not computed:
            checks.append((name, "computed", 0, "-", 0))
            continue
        if existing and existing == computed:
            source = "raw/%s_baseline_diff.txt" % name
            emit = {k: existing[k] for k in computed}
            mismatch = 0
        else:
            source = "computed" if not existing else "computed(汇总不一致)"
            emit = computed
            mismatch = 0 if not existing else len(
                [k for k in computed if existing.get(k) != computed[k]])
        for key in sorted(computed, key=lambda kk: (kk[0], kk[1])):
            lines.append(emit[key])
        checks.append((name, source, len(computed),
                       "true" if (existing and existing == computed) else
                       ("false" if existing else "-"), mismatch))
    head = [
        "# cross.py 方案 vs 基线对照（角色扮演横评 · 世界书触发＋上下文预算）",
        "# 行语法 DIFF <a> <b> <profile> turn=<k> only_a=<uids> only_b=<uids> same=<n>；b=baseline；空集合写 -",
        "# 来源：raw/<name>_baseline_diff.txt 已存在且逐行一致时按行汇总，否则由 out/ 现算",
        "# 汇总来源：%s" % ("；".join("%s %s lines=%d match=%s" % c[:4] for c in checks)
                            if checks else "-"),
        "# 缺席方案：%s" % (",".join(n for n in SCHEMES if n not in data) or "-"),
    ]
    text = "\n".join(head + lines) + "\n"
    return text, len(lines), checks


def parse_args(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    ap.add_argument("--raw-dir", default=str(ROOT / "raw"))
    ap.add_argument("--check", action="store_true", help="只算并打印，不落盘")
    return ap.parse_args(argv)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = parse_args(argv if argv is not None else sys.argv[1:])
    out_dir = Path(args.out_dir)
    raw_dir = Path(args.raw_dir)

    data = discover(out_dir)
    profiles = profiles_of(data)
    turns = turns_of(data)

    matrix_text, cross_n, pair_n, missing = build_matrix(data, profiles, turns)
    base_text, diff_n, checks = build_baseline_diff(data, raw_dir)

    print("CROSS adapters=%s missing=%s"
          % (",".join(n for n in ADAPTER_ORDER if n in data) or "-",
             ",".join(missing) or "-"))
    print("CROSS profiles=%s turns=%s cross_lines=%d crosspair_lines=%d"
          % (",".join(profiles) or "-", ",".join(str(t) for t in turns) or "-",
             cross_n, pair_n))
    for name, source, n, match, mismatch in checks:
        print("DIFFCHECK name=%s source=%s lines=%d match=%s mismatch=%d"
              % (name, source, n, match, mismatch))
    if not args.check:
        wrote_m, digest_m = write_if_changed(raw_dir / "cross_matrix.txt", matrix_text)
        wrote_d, digest_d = write_if_changed(raw_dir / "cross_baseline_diff.txt", base_text)
        print("CROSSFILE raw/cross_matrix.txt sha256=%s lines=%d written=%s"
              % (digest_m, matrix_text.count(chr(10)), "true" if wrote_m else "false"))
        print("CROSSFILE raw/cross_baseline_diff.txt sha256=%s lines=%d written=%s"
              % (digest_d, base_text.count(chr(10)), "true" if wrote_d else "false"))
    print("CROSS ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
