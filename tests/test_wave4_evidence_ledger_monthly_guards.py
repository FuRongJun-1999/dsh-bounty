# -*- coding: utf-8 -*-
"""守卫 · evidence_check 路径穿越/bytes 校验 ＋ check_ledger_invariants 非法日历/非对象 ＋ monthly_summary 零净月对账（正向 ＋ 定点变异自证）。

  python -X utf8 tests/test_wave4_evidence_ledger_monthly_guards.py            # 正向断言
  python -X utf8 tests/test_wave4_evidence_ledger_monthly_guards.py --mutate   # 定点变异自证（隔离临时目录，零写仓）
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EC_PATH = os.path.join(ROOT, "scripts", "evidence_check.py")
CLI_PATH = os.path.join(ROOT, "scripts", "check_ledger_invariants.py")
MS_PATH = os.path.join(ROOT, "scripts", "monthly_summary.py")


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_suite(ec, cli, ms, quiet: bool = False):
    red = []
    total = [0]

    def ok(code: str, desc: str, cond: bool, detail=""):
        total[0] += 1
        if not cond:
            red.append(code)
        if not quiet:
            tail = f"  · {detail!r}" if (not cond and detail != "") else ""
            print(f"  [{'PASS' if cond else 'FAIL'}] {code} {desc}{tail}")

    # ---- E: evidence_check path traversal + bytes bool/float/0 ----
    with tempfile.TemporaryDirectory(prefix="ec_w4_") as td:
        ev_dir = os.path.join(td, "review", "evidence")
        data_dir = os.path.join(td, "review", "data")
        os.makedirs(ev_dir)
        os.makedirs(data_dir)
        outside = os.path.join(td, "outside_secret.txt")
        with io.open(outside, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("SECRET OUTSIDE EVIDENCE\n")
        h_out = ec.sha256_file(outside)
        sz_out = os.path.getsize(outside)
        with io.open(os.path.join(data_dir, "plugins.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"rubric_version": "v1", "records": []}, fh)

        # E1a: manifest_index rejects relative/absolute/subdir traversal fail-closed (ValueError)
        mi_rejected = True
        for bad_name in ("../../outside_secret.txt", "../data/plugins.json", os.path.abspath(outside), "sub/file.txt", "a\\b.txt"):
            try:
                ec.manifest_index({"documents": [{"file": bad_name}]})
                mi_rejected = False
                break
            except ValueError:
                pass
        ok("E1a", "evidence_check.manifest_index 拒绝相对/绝对/子目录路径穿越", mi_rejected)

        # E1d: _resolve_inside defense-in-depth blocks traversal & out-of-dir paths
        ri_ok = all(ec._resolve_inside(ev_dir, bn) is None for bn in (
            "../../outside_secret.txt", "../data/plugins.json", os.path.abspath(outside), "sub/file.txt", ".."))
        ok("E1d", "evidence_check._resolve_inside 纵深阻断越界路径", ri_ok)

        # E1b: bytes=True / bytes=1.0 / bytes=-1 rejected
        one = os.path.join(ev_dir, "one.txt")
        with open(one, "wb") as fh:
            fh.write(b"x")
        h_one = ec.sha256_file(one)
        bytes_rejected = True
        for bad_b in (True, 1.0, -1):
            with io.open(os.path.join(ev_dir, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
                json.dump({"documents": [{"file": "one.txt", "kind": "README", "source_url": "https://example.com",
                                          "sha256": h_one, "bytes": bad_b, "fetched_at": "2026-10-15"}]}, fh)
            _r, bads = ec.audit(root=td, want_repro=False)
            if not any("bytes 不是整数" in b for b in bads):
                bytes_rejected = False
                break
        ok("E1b", "evidence_check 拒绝 bool/float/负数 bytes", bytes_rejected)

        # E1c: valid 0-byte snapshot with bytes=0 passes cleanly (not false-positive missing field)
        os.remove(one)
        zero = os.path.join(ev_dir, "zero.txt")
        with open(zero, "wb") as fh:
            fh.write(b"")
        with io.open(os.path.join(ev_dir, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"documents": [{"file": "zero.txt", "kind": "README", "source_url": "https://example.com",
                                      "sha256": ec.sha256_file(zero), "bytes": 0, "fetched_at": "2026-10-15"}]}, fh)
        _r, bads0 = ec.audit(root=td, want_repro=False)
        ok("E1c", "evidence_check 允许合法 0 字节快照（bytes=0 不误报缺字段）", bads0 == [], bads0)

    # ---- L: check_ledger_invariants invalid calendar date + non-dict / non-list ----
    bad_cal_ev = [{
        "id": "evt_000000000000", "ts": "2026-02-30T25:99:99Z", "day": "2026-02-30",
        "action": "settle", "actor": "a", "holder": "b", "difficulty": "easy",
        "delta": 1, "impact": "B", "covers": [1], "project": "memory",
    }]
    try:
        bd, _st = cli.audit(bad_cal_ev)
        cal_ok = bool(bd.get("I9_ts_shape"))
    except Exception as exc:
        cal_ok = False
        bd = f"CRASH:{type(exc).__name__}"
    ok("L1a", "check_ledger_invariants 对非法日历 ts 归入 I9_ts_shape（不抛裸 ValueError）", cal_ok, bd)

    try:
        bd2, _st2 = cli.audit(["not-a-dict", 123])
        nd_ok = bool(bd2.get("I7_required_fields")) and len(bd2["I7_required_fields"]) == 2
    except Exception as exc:
        nd_ok = False
        bd2 = f"CRASH:{type(exc).__name__}"
    ok("L1b", "check_ledger_invariants 对非对象元素结构化记账（不抛裸 AttributeError）", nd_ok, bd2)

    try:
        bd3, _st3 = cli.audit("not-a-list")
        nl_ok = bool(bd3.get("I7_required_fields"))
    except Exception as exc:
        nl_ok = False
        bd3 = f"CRASH:{type(exc).__name__}"
    ok("L1c", "check_ledger_invariants 对非数组 events fail-closed（不崩）", nl_ok, bd3)

    # ---- M: monthly_summary zero-net-month reconciliation + non-dict element + negative trend ----
    zero_net_evs = [
        {"issue": 1, "day": "2026-11-01", "delta": 3, "holder": "alice", "project": "memory", "difficulty": "medium"},
        {"issue": 2, "day": "2026-11-02", "delta": -3, "holder": "alice", "project": "memory", "difficulty": "medium"},
        {"issue": 3, "day": "2026-11-03", "delta": 1, "holder": "bob", "project": "memory", "difficulty": "easy"},
    ]
    txt, n_tot, d_tot = ms.build(zero_net_evs)
    blk = txt.split("## 当月结算明细")[1].split("## 月度趋势")[0]
    rows = [l for l in blk.splitlines() if l.startswith("| ") and "@" in l]
    tot_ln = [l for l in blk.splitlines() if l.startswith("| ") and "合计" in l][0]

    def _cells(r):
        return [c.strip().strip("*") for c in r.strip().strip("|").split("|")]

    data = [_cells(r) for r in rows]
    tot = _cells(tot_ln)
    sum_items = sum(int(c[3]) for c in data)
    sum_med = sum(int(c[5]) for c in data)
    ok("M1a", "monthly_summary 零净月贡献者不丢失，逐行结算项与难度列之和等于合计行",
       len(data) == 2 and sum_items == int(tot[3]) == 3 and sum_med == int(tot[5]) == 2,
       (data, tot))

    # negative-only month does not invert trend bar
    neg_evs = [
        {"issue": 9, "day": "2026-11-01", "delta": -3, "holder": "alice", "project": "memory", "difficulty": "medium"},
    ]
    txt_neg, _, _ = ms.build(neg_evs)
    trend_blk = txt_neg.split("## 月度趋势")[1].split("---")[0]
    ok("M1b", "monthly_summary 全负月趋势条不反转为满格正条",
       "#" not in trend_blk and "-3" in trend_blk, trend_blk)

    nd_ms_ok = False
    try:
        ms.build(["not-a-dict"])
    except SystemExit as exc:
        nd_ms_ok = "不是对象" in str(exc)
    except Exception:
        nd_ms_ok = False
    ok("M1c", "monthly_summary 非对象事件 fail-closed SystemExit（不抛裸 AttributeError）", nd_ms_ok)

    return red, total[0]


MUTANTS = (
    ("WM_EC1", EC_PATH, "ec", "evidence_check 关闭 manifest_index 路径穿越闸",
     "        if not _is_safe_snapshot_name(name):",
     "        if False:  # MUT",
     {"E1a"}),
    ("WM_EC1b", EC_PATH, "ec", "evidence_check 关闭 _resolve_inside 纵深校验",
     "    if not _is_safe_snapshot_name(name):\n        return None",
     "    if False:  # MUT\n        return None",
     {"E1d"}),
    ("WM_EC2", EC_PATH, "ec", "evidence_check 关闭 bytes 的 bool/非整数校验",
     "        if isinstance(raw_bytes, bool) or not isinstance(raw_bytes, int) or raw_bytes < 0:",
     "        if False:  # MUT",
     {"E1b"}),
    ("WM_EC3", EC_PATH, "ec", "evidence_check 恢复 bytes=0 假阳性缺字段",
     "            if raw_v is None or (isinstance(raw_v, str) and not raw_v.strip()):",
     '            if not str(raw_v or "").strip():  # MUT',
     {"E1c"}),
    ("WM_CLI1", CLI_PATH, "cli", "check_ledger_invariants 关闭非法日历 ts 异常捕获",
     "            try:\n                calc_day = _day_of(ts)\n            except ValueError:",
     "            try:\n                calc_day = _day_of(ts)\n            except KeyError:  # MUT",
     {"L1a"}),
    ("WM_CLI2", CLI_PATH, "cli", "check_ledger_invariants 关闭非对象元素守卫",
     "        if not isinstance(e, dict):",
     "        if False:  # MUT",
     {"L1b"}),
    ("WM_MS1", MS_PATH, "ms", "monthly_summary 恢复 in_month 真值过滤（丢零净月）",
     "    in_month = [h for h in holders if latest in hm[h]]",
     "    in_month = [h for h in holders if hm[h].get(latest)]  # MUT",
     {"M1a"}),
)


def run_mutations() -> int:
    print(f"定点变异自证（test_wave4_evidence_ledger_monthly_guards）：{len(MUTANTS)} 条")
    ec_real = _load(EC_PATH, "ec_w4_base")
    cli_real = _load(CLI_PATH, "cli_w4_base")
    ms_real = _load(MS_PATH, "ms_w4_base")
    failed = 0
    with tempfile.TemporaryDirectory(prefix="w4_c2_mut_") as td:
        for mid, target_path, kind, desc, old, new, want in MUTANTS:
            src = io.open(target_path, encoding="utf-8").read().replace("\r\n", "\n")
            cnt = src.count(old)
            if cnt != 1:
                print(f"  [ANCHOR-MISS] {mid} {desc} (hits={cnt})")
                return 2
            mp = os.path.join(td, f"{mid}.py")
            with io.open(mp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(src.replace(old, new, 1))
            mmod = _load(mp, f"mut_{mid}")
            ec = mmod if kind == "ec" else ec_real
            cli = mmod if kind == "cli" else cli_real
            ms = mmod if kind == "ms" else ms_real
            red, _tot = run_suite(ec, cli, ms, quiet=True)
            got = set(red)
            hit = (got == want)
            print(f"  [{'PASS' if hit else 'FAIL'}] {mid} {desc} -> got={sorted(got)} want={sorted(want)}")
            if not hit:
                failed += 1
    print(f"变异守卫：{len(MUTANTS)} 条 · 通过 {len(MUTANTS) - failed} · 失败 {failed}")
    return 1 if failed else 0


def main() -> int:
    if "--mutate" in sys.argv:
        return run_mutations()
    print("守卫 · wave4（evidence_check / check_ledger_invariants / monthly_summary）")
    ec = _load(EC_PATH, "ec_w4_real")
    cli = _load(CLI_PATH, "cli_w4_real")
    ms = _load(MS_PATH, "ms_w4_real")
    red, tot = run_suite(ec, cli, ms, quiet=False)
    print(f"通过 {tot - len(red)} / 失败 {len(red)}")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
