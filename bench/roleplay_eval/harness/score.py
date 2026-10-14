#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评分层：把方案与基线两份适配器输出变成可指认的差异与 KPI 读数。

用法：
  python -X utf8 bench/roleplay_eval/harness/score.py --name baseline
  python -X utf8 bench/roleplay_eval/harness/score.py --name baseline \
      --out-dir bench/roleplay_eval/out --raw-dir bench/roleplay_eval/raw --profiles P0,P1,P2,P3,P4

产物（追加写入；同一输入重复运行，文件逐字节相同）：
  raw/<name>_baseline_diff.txt  方案 vs 基线，逐 (profile, turn) 的激活集 DIFF 行
  raw/<name>_diff.txt           消融 DIFF 行：P0vsP3（预算 dropped）、P0vsP1（递归）、
                                P0vsP2（深度）、P0vsP4（匹配口径）
  raw/<name>_kpi.txt            KPI 行（M1–M8）
  raw/<name>_summary.json       追加 kpi 字段；既有字段原样保留

KPI 口径：
  Δ 类 KPI（名字含 _delta）= 方案读数 − 基线读数，按 (profile, turn) 配对；
  方案与基线同体时每条 Δ 恒为 0、CI=[0,0]（--name baseline 的自比判据）。
  配对自助法：重采样 2000 次、seed=0，用 harness/metrics.py 的 paired_bootstrap_ci。
  配对数 <2 时写 ci=[-,-] n=<n>，并在 stdout 用 NOTE 行说明原因。
  M8 的 value 是逐 (profile, turn) 激活条数之和；CI 由逐行计数的配对自助法均值 CI 乘以行数得到。

输入：--out-dir/<name>_<P>.json，退到 --raw-dir/<name>_<P>.json，再退到 <name>_<P>.txt 的 READOUT 行；
      --raw-dir/<name>_summary.json 只读 determinism。
输出：只写上述 4 个 raw/<name>_* 文件；不碰 data/、out/、适配器、夹具。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))

import metrics  # noqa: E402

PROFILES_DEFAULT = "P0,P1,P2,P3,P4"
BOOTSTRAP_ITERS = metrics.BOOTSTRAP_ITERS
BOOTSTRAP_SEED = metrics.BOOTSTRAP_SEED

# (high, low, 口径, 标签)；顺序即 <name>_diff.txt 的行序
ABLATION_DEFS = (
    ("P0", "P3", "dropped", "budget"),
    ("P0", "P1", "active", "recursive"),
    ("P0", "P2", "active", "scan_depth"),
    ("P0", "P4", "active", "match_profile"),
)

READOUT_RE = re.compile(
    r"^READOUT (\S+) (\S+) turn=(\d+) active=(\d+) order=(\S+) chars=(\d+) bytes=(\d+) dropped=(\S+)$")


# ---------- 输入 ----------

def rel(p):
    if p is None:
        return "-"
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return Path(p).as_posix()


def _dir_arg(value):
    """相对路径先按当前工作目录解，再按 harness 根解（两种调用姿势都能命中）。"""
    p = Path(value)
    if p.is_absolute():
        return p
    for base in (Path.cwd(), ROOT):
        cand = base / p
        if cand.is_dir():
            return cand
    return ROOT / p


def _turns_from_doc(doc):
    turns = {}
    if not isinstance(doc, dict):
        return turns
    for t in doc.get("turns") or []:
        if not isinstance(t, dict):
            continue
        try:
            tot = t.get("totals") or {}
            turns[int(t["turn"])] = {
                "active": sorted(int(u) for u in t["active_uids"]),
                "order": [int(u) for u in t["inject_order"]],
                "dropped": sorted(int(u) for u in (tot.get("dropped_uids") or [])),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return turns


def _turns_from_text(text):
    turns = {}
    for line in text.replace("\r\n", "\n").split("\n"):
        m = READOUT_RE.match(line)
        if not m:
            continue
        _ad, _pf, tn, _active, order, _ch, _by, dropped = m.groups()
        turns[int(tn)] = {"active": sorted(set(metrics.parse_uids(order))),
                          "order": metrics.parse_uids(order),
                          "dropped": metrics.parse_uids(dropped)}
    return turns


def load_turns(name, profile, out_dir, raw_dir):
    """返回 (turns, source)。turns={turn:{"active","order","dropped"}}；读不到返回 ({}, None)。"""
    for cand in (out_dir / ("%s_%s.json" % (name, profile)),
                 raw_dir / ("%s_%s.json" % (name, profile))):
        if not cand.is_file():
            continue
        try:
            turns = _turns_from_doc(json.loads(cand.read_text(encoding="utf-8")))
        except Exception:
            continue
        if turns:
            return turns, cand
    txt = raw_dir / ("%s_%s.txt" % (name, profile))
    if txt.is_file():
        turns = _turns_from_text(txt.read_text(encoding="utf-8", errors="replace"))
        if turns:
            return turns, txt
    return {}, None


# ---------- 集合口径 ----------

def f1_score(a, b):
    """激活集 F1：2|A∩B|/(|A|+|B|)；两侧都空按 1 计。"""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return 2.0 * len(sa & sb) / float(len(sa) + len(sb))


def symdiff_size(a, b):
    return len(set(a) ^ set(b))


def restricted_inversions(order_a, order_b):
    """同一激活集口径＝两侧顺序先过滤到交集，再各算逆序对。"""
    common = set(order_a) & set(order_b)
    oa = [u for u in order_a if u in common]
    ob = [u for u in order_b if u in common]
    return metrics.inversion_count(oa), metrics.inversion_count(ob), len(common)


# ---------- 落盘 ----------

def write_append(path, header_lines, new_lines):
    """追加写入：既有行原样保留，只追加未出现过的行；表头变化时重建该文件。

    同一输入重复运行 ⇒ 无新行可加 ⇒ 内容不变 ⇒ 逐字节相同。
    """
    existing = []
    if path.is_file():
        existing = path.read_text(encoding="utf-8", errors="replace").split("\n")
        while existing and existing[-1] == "":
            existing.pop()
    header_lines = list(header_lines)
    if existing[:len(header_lines)] != header_lines:
        existing = []
    out = list(existing)
    seen = set(out)
    if not out:
        out = list(header_lines)
        seen = set(out)
    added = 0
    for line in new_lines:
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
        added += 1
    content = "\n".join(out) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8", errors="replace") != content:
        path.write_text(content, encoding="utf-8", newline="\n")
    return added, metrics.sha256_text(content), len(out)


def write_json(path, doc):
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8", errors="replace") != text:
        path.write_text(text, encoding="utf-8", newline="\n")
    return metrics.sha256_text(text)


# ---------- 主流程 ----------

def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="角色扮演横评评分层：方案 vs 基线的差异与 KPI")
    ap.add_argument("--name", required=True, help="方案名（读 out/<name>_<P>.json）")
    ap.add_argument("--baseline-name", default="baseline")
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    ap.add_argument("--raw-dir", default=str(ROOT / "raw"))
    ap.add_argument("--profiles", default=PROFILES_DEFAULT)
    args = ap.parse_args(argv)

    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    out_dir = _dir_arg(args.out_dir)
    raw_dir = _dir_arg(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    print("SCORE name=%s baseline=%s profiles=%s out_dir=%s raw_dir=%s"
          % (args.name, args.baseline_name, ",".join(profiles), rel(out_dir), rel(raw_dir)))

    sides = [(args.name, {})]
    if args.baseline_name != args.name:
        sides.append((args.baseline_name, {}))
    for _who, store in sides:
        for p in profiles:
            turns, src = load_turns(_who, p, out_dir, raw_dir)
            store[p] = turns
            print("SOURCE %s %s file=%s turns=%d" % (_who, p, rel(src), len(turns)))
    name_turns = sides[0][1]
    base_turns = sides[-1][1]

    missing = []
    for p in profiles:
        for who, store in ((args.name, name_turns), (args.baseline_name, base_turns)):
            if not store.get(p) and (who, p) not in missing:
                missing.append((who, p))
    for who, p in missing:
        print(metrics.unsupported_line(who, "profile_%s" % p, "out-json-missing"))

    # ---- 1. 方案 vs 基线：逐 (profile, turn) 激活集差异 ----
    baseline_lines = []
    for p in profiles:
        common = sorted(set(name_turns.get(p) or {}) & set(base_turns.get(p) or {}))
        if not common:
            baseline_lines.append("# profile=%s status=unmeasured reason=out-json-missing" % p)
            continue
        for t in common:
            baseline_lines.append(metrics.diff_line(
                args.name, args.baseline_name, p, t,
                name_turns[p][t]["active"], base_turns[p][t]["active"]))

    # ---- 2. 消融差异 ----
    ablation_lines = []
    for hi, lo, axis, label in ABLATION_DEFS:
        tag = "%svs%s" % (hi, lo)
        common = sorted(set(name_turns.get(hi) or {}) & set(name_turns.get(lo) or {}))
        if not common:
            ablation_lines.append("# pair=%s label=%s status=unmeasured reason=out-json-missing"
                                  % (tag, label))
            continue
        for t in common:
            th, tl = name_turns[hi][t], name_turns[lo][t]
            ablation_lines.append(metrics.diff_line(
                "%s@%s" % (args.name, hi), "%s@%s" % (args.name, lo), tag, t,
                th["active"], tl["active"]))
            if axis == "dropped":
                ablation_lines.append(metrics.diff_line(
                    "%s@%s.dropped" % (args.name, hi), "%s@%s.dropped" % (args.name, lo), tag, t,
                    th["dropped"], tl["dropped"]))

    # ---- 3. KPI ----
    kpi_entries = []
    kpi_lines = []
    short_notes = []

    def emit(metric, kind, definition, pairs, value=None, scale=1.0):
        n = len(pairs)
        if value is None:
            value = metrics.mean([a - b for a, b in pairs]) if pairs else 0.0
        if n >= 2:
            lo, hi = metrics.paired_bootstrap_ci(pairs)
            lo, hi = lo * scale, hi * scale
            line = metrics.kpi_line(metric, value, (lo, hi), n)
            clo, chi = lo, hi
        else:
            line = "KPI %s value=%s ci=[-,-] n=%d" % (metric, metrics.fmt_num(value), n)
            clo = chi = None
            short_notes.append((metric, n))
        kpi_lines.append(line)
        kpi_entries.append({
            "metric": metric, "kind": kind, "definition": definition,
            "value": round(float(value), 6),
            "ci_lo": None if clo is None else round(float(clo), 6),
            "ci_hi": None if chi is None else round(float(chi), 6),
            "n": n, "line": line,
        })

    p0n = name_turns.get("P0") or {}
    p0b = base_turns.get("P0") or {}
    m1_f1, m1_f1d, m1_sd, m2_abs, m2_delta = [], [], [], [], []
    for t in sorted(set(p0n) & set(p0b)):
        a, b = p0n[t]["active"], p0b[t]["active"]
        f = f1_score(a, b)
        m1_f1.append((f, 0.0))
        m1_f1d.append((f - 1.0, 0.0))
        m1_sd.append((float(symdiff_size(a, b)), 0.0))
        ia, ib, _c = restricted_inversions(p0n[t]["order"], p0b[t]["order"])
        m2_abs.append((float(ia), 0.0))
        m2_delta.append((float(ia), float(ib)))

    def ablation_pairs(lo):
        out = []
        for t in sorted(set(name_turns.get("P0") or {}) & set(name_turns.get(lo) or {})
                        & set(base_turns.get("P0") or {}) & set(base_turns.get(lo) or {})):
            mn = symdiff_size(name_turns["P0"][t]["active"], name_turns[lo][t]["active"])
            mb = symdiff_size(base_turns["P0"][t]["active"], base_turns[lo][t]["active"])
            out.append((float(mn), float(mb)))
        return out

    m3 = []
    for t in sorted(set(name_turns.get("P0") or {}) & set(name_turns.get("P3") or {})
                    & set(base_turns.get("P0") or {}) & set(base_turns.get("P3") or {})):
        mn = symdiff_size(name_turns["P0"][t]["dropped"], name_turns["P3"][t]["dropped"])
        mb = symdiff_size(base_turns["P0"][t]["dropped"], base_turns["P3"][t]["dropped"])
        m3.append((float(mn), float(mb)))
    m4 = ablation_pairs("P1")
    m5 = ablation_pairs("P2")
    m7 = ablation_pairs("P4")

    summary_path = raw_dir / ("%s_summary.json" % args.name)
    summary = {}
    if summary_path.is_file():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                summary = loaded
        except Exception:
            summary = {}
    det = summary.get("determinism") if isinstance(summary.get("determinism"), dict) else {}
    m6 = []
    for p in profiles:
        d = det.get(p)
        if isinstance(d, dict) and "identical" in d:
            m6.append((1.0 if d.get("identical") is True else 0.0, 0.0))

    m8_rows = []
    for p in profiles:
        for t in sorted(name_turns.get(p) or {}):
            m8_rows.append((float(len(name_turns[p][t]["active"])), 0.0))
    m8_total = sum(a for a, _b in m8_rows)

    emit("M1_active_f1", "absolute",
         "方案 P0 激活集 vs 基线 P0 的同 turn F1 均值：2|A∩B|/(|A|+|B|)", m1_f1)
    emit("M1_active_f1_delta", "delta",
         "M1 的 Δ 形式：F1 − 1；两侧集合相同即为 0", m1_f1d)
    emit("M1_active_symdiff", "delta",
         "方案 P0 与基线 P0 的激活集对称差大小均值", m1_sd)
    emit("M2_order_inv", "absolute",
         "同一激活集（两侧注入顺序的交集）上方案侧逆序对数均值", m2_abs)
    emit("M2_order_inv_delta", "delta",
         "同一激活集上方案逆序对数 − 基线逆序对数，逐 turn 配对", m2_delta)
    emit("M3_budget_dropped_delta", "delta",
         "P0 vs P3 的 dropped_uids 对称差大小：方案 − 基线，逐 turn 配对", m3)
    emit("M4_recursion_ablation_delta", "delta",
         "P0 vs P1 的激活集对称差大小：方案 − 基线，逐 turn 配对", m4)
    emit("M5_depth_ablation_delta", "delta",
         "P0 vs P2 的激活集对称差大小：方案 − 基线，逐 turn 配对", m5)
    emit("M6_determinism", "absolute",
         "读 raw/<name>_summary.json 的 determinism：identical=true 记 1，逐 profile 求均值", m6)
    emit("M7_match_ablation_delta", "delta",
         "P0 vs P4 的激活集对称差大小：方案 − 基线，逐 turn 配对", m7)
    emit("M8_total_active_uids", "absolute",
         "所选 profiles × 全部 turn 的方案激活条目数之和（CI 为逐行计数均值 CI × 行数）",
         m8_rows, value=m8_total, scale=float(len(m8_rows)))

    # ---- 4. stdout ----
    for line in baseline_lines:
        print(line)
    for line in ablation_lines:
        print(line)
    for line in kpi_lines:
        print(line)
    for metric, n in short_notes:
        print("NOTE KPI metric=%s n=%d ci=[-,-] reason=insufficient-pairs(min=2)" % (metric, n))
    if m1_f1:
        print("NOTE KPI metric=M1_active_f1 kind=absolute value=%s "
              "口径说明=集合与自身比较时 F1 恒为 1；Δ 形式见 M1_active_f1_delta"
              % metrics.fmt_num(metrics.mean([a for a, _b in m1_f1])))
    for p in profiles:
        if not (name_turns.get(p) or {}):
            print("NOTE profile=%s status=unmeasured reason=out-json-missing" % p)

    deltas = [e for e in kpi_entries if e["kind"] == "delta"]
    all_zero = all(e["value"] == 0 for e in deltas)
    ci_zero = all(e["ci_lo"] == 0 and e["ci_hi"] == 0 for e in deltas if e["ci_lo"] is not None)
    ci_na = [e["metric"] for e in deltas if e["ci_lo"] is None]
    print("SELFCHECK name=%s baseline=%s delta_metrics=%d all_zero=%s ci_zero=%s ci_na=%s"
          % (args.name, args.baseline_name, len(deltas),
             "true" if all_zero else "false", "true" if ci_zero else "false",
             metrics.fmt_uids([]) if not ci_na else ",".join(ci_na)))

    # ---- 5. 落盘 ----
    base_header = [
        "# score.py baseline-diff name=%s baseline=%s profiles=%s metric=active_uids"
        % (args.name, args.baseline_name, ",".join(profiles)),
        "# 行语法 DIFF <a> <b> <profile> turn=<k> only_a=<uids> only_b=<uids> same=<n>；a=%s b=%s；空集合写 -"
        % (args.name, args.baseline_name),
        "# only_a=a 侧独有 only_b=b 侧独有 same=交集大小",
    ]
    abl_header = [
        "# score.py ablation-diff name=%s baseline=%s profiles=%s"
        % (args.name, args.baseline_name, ",".join(profiles)),
        "# a=<name>@<high> b=<name>@<low> profile=<high>vs<low>；横轴=同名方案两档之间的差异",
        "# P0vsP3=budget（active 口径另加一行 .dropped 口径） P0vsP1=recursive "
        "P0vsP2=scan_depth P0vsP4=match_profile",
        "# 行语法同 baseline-diff；空集合写 -",
    ]
    kpi_header = [
        "# score.py kpi name=%s baseline=%s profiles=%s bootstrap_iters=%d bootstrap_seed=%d alpha=%s"
        % (args.name, args.baseline_name, ",".join(profiles),
           BOOTSTRAP_ITERS, BOOTSTRAP_SEED, metrics.fmt_num(metrics.ALPHA)),
        "# 配对单位=(profile,turn)；Δ 类 KPI（名字含 _delta）= 方案 − 基线；n<2 时 ci=[-,-]",
    ]

    written = []
    b_added, b_sha, b_n = write_append(raw_dir / ("%s_baseline_diff.txt" % args.name),
                                       base_header, baseline_lines)
    written.append(("baseline_diff", b_added, b_sha, b_n,
                    raw_dir / ("%s_baseline_diff.txt" % args.name)))
    a_added, a_sha, a_n = write_append(raw_dir / ("%s_diff.txt" % args.name),
                                       abl_header, ablation_lines)
    written.append(("ablation_diff", a_added, a_sha, a_n,
                    raw_dir / ("%s_diff.txt" % args.name)))
    k_added, k_sha, k_n = write_append(raw_dir / ("%s_kpi.txt" % args.name),
                                       kpi_header, kpi_lines)
    written.append(("kpi", k_added, k_sha, k_n, raw_dir / ("%s_kpi.txt" % args.name)))

    kpi_doc = {
        "baseline": args.baseline_name,
        "profiles": profiles,
        "unit": "paired-(profile,turn)",
        "bootstrap": {"iters": BOOTSTRAP_ITERS, "seed": BOOTSTRAP_SEED,
                      "alpha": metrics.ALPHA, "statistic": "mean-of-paired-difference"},
        "delta_all_zero": all_zero,
        "delta_ci_zero": ci_zero,
        "ci_undefined_metrics": sorted(ci_na),
        "missing": [{"adapter": w, "profile": p, "reason": "out-json-missing"} for w, p in missing],
        "metrics": kpi_entries,
    }
    if not summary:
        summary = {"adapter": args.name, "created_by": "harness/score.py",
                   "note": "no runner summary for this name; determinism unmeasured",
                   "determinism": {}}
    summary["kpi"] = kpi_doc
    s_sha = write_json(summary_path, summary)

    for kind, added, sha, n, path in written:
        print("WROTE kind=%s file=%s added=%d lines=%d sha256=%s"
              % (kind, rel(path), added, n, sha))
    print("WROTE kind=summary file=%s sha256=%s" % (rel(summary_path), s_sha))
    print("SUMMARY name=%s baseline=%s baseline_diff_lines=%d ablation_diff_lines=%d "
          "kpi_lines=%d missing_profiles=%d delta_all_zero=%s"
          % (args.name, args.baseline_name, len(baseline_lines), len(ablation_lines),
             len(kpi_lines), len(missing), "true" if all_zero else "false"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
