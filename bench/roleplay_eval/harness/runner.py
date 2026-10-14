#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行器：调适配器、落 raw/、解析 §7.2 读数行、按档计时。

用法：
  python -X utf8 harness/runner.py --adapter baseline --profiles P0,P1,P2,P3,P4

产物：
  out/<name>_<profile>.json      适配器写的 §3.2 契约 JSON
  raw/<name>_<profile>.txt       该档 stdout 逐字副本
  raw/<name>_<profile>.json      与 out/ 同名文件逐字节相同的副本
  raw/<name>_repeat.txt          确定性重复运行的 DETERMINISM 行
  raw/<name>_summary.json        {"adapter":..,"profiles":{..},"determinism":{..}}

计时口径：1 次预热 ＋ 7 次采样；一次采样＝启动一次适配器进程、跑完该档 6 个 turn 的端到端墙钟时间，
进程启动计入，预热不计入统计。采样值同时用于确定性判据（8 次 stdout 摘要必须全等）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import metrics  # noqa: E402

READOUT_RE = re.compile(
    r"^READOUT (\S+) (\S+) turn=(\d+) active=(\d+) order=(\S+) chars=(\d+) bytes=(\d+) dropped=(\S+)$")
UID_LIST_RE = re.compile(r"^(-|\d+(,\d+)*)$")
WARMUP = 1
SAMPLES = 7


def adapter_cmd(arg):
    """名字 → adapters/<name>/run.py|run.mjs；路径 → 直接跑。"""
    p = Path(arg)
    if p.is_file():
        return p.stem, _cmd_for(p)
    cand = ROOT / "adapters" / arg / "run.py"
    if cand.is_file():
        return arg, [sys.executable, "-X", "utf8", str(cand)]
    cand = ROOT / "adapters" / arg / "run.mjs"
    if cand.is_file():
        return arg, ["node", str(cand)]
    raise SystemExit("ERROR %s profile=- kind=adapter-not-found" % arg)


def _cmd_for(p):
    if p.suffix == ".py":
        return [sys.executable, "-X", "utf8", str(p.resolve())]
    if p.suffix in (".mjs", ".js"):
        return ["node", str(p.resolve())]
    raise SystemExit("ERROR %s profile=- kind=adapter-ext-unsupported" % p.name)


def invoke(cmd, data_dir, profile, out_path):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    argv = cmd + ["--data", str(data_dir), "--profile", profile, "--out", str(out_path)]
    t0 = time.perf_counter()
    proc = subprocess.run(argv, cwd=str(ROOT), env=env, capture_output=True)
    return proc, (time.perf_counter() - t0) * 1000.0


def parse_readouts(text):
    rows, errs = {}, []
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.startswith("READOUT "):
            continue
        m = READOUT_RE.match(line)
        if not m:
            errs.append("readout-format:%s" % line[:70])
            continue
        ad, pf, turn, active, order, ch, by, dropped = m.groups()
        if not UID_LIST_RE.match(order) or not UID_LIST_RE.match(dropped):
            errs.append("readout-uidlist:%s" % line[:70])
            continue
        turn = int(turn)
        if turn in rows:
            errs.append("readout-duplicate-turn=%d" % turn)
            continue
        rows[turn] = {"adapter": ad, "profile": pf, "active": int(active),
                      "order": metrics.parse_uids(order), "chars": int(ch),
                      "bytes": int(by), "dropped": metrics.parse_uids(dropped), "line": line}
    return rows, errs


def cross_check(label, profile, rows, doc):
    """读数行必须与 out/ 契约 JSON 逐项对上。"""
    errs = []
    if sorted(rows) != [1, 2, 3, 4, 5, 6]:
        errs.append("readout-turns=%s" % sorted(rows))
    turns = doc.get("turns") if isinstance(doc, dict) else None
    if not isinstance(turns, list):
        return errs + ["out-turns-missing"]
    for t in turns:
        r = rows.get(t["turn"])
        if r is None:
            errs.append("readout-missing-turn=%d" % t["turn"])
            continue
        if r["adapter"] != label:
            errs.append("turn%d:adapter=%s" % (t["turn"], r["adapter"]))
        if r["profile"] != profile:
            errs.append("turn%d:profile=%s" % (t["turn"], r["profile"]))
        if r["active"] != len(t["active_uids"]):
            errs.append("turn%d:active=%d!=%d" % (t["turn"], r["active"], len(t["active_uids"])))
        if r["order"] != t["inject_order"]:
            errs.append("turn%d:order" % t["turn"])
        if r["chars"] != t["totals"]["chars"]:
            errs.append("turn%d:chars=%d!=%d" % (t["turn"], r["chars"], t["totals"]["chars"]))
        if r["bytes"] != t["totals"]["bytes"]:
            errs.append("turn%d:bytes=%d!=%d" % (t["turn"], r["bytes"], t["totals"]["bytes"]))
        if r["dropped"] != t["totals"]["dropped_uids"]:
            errs.append("turn%d:dropped" % t["turn"])
    return errs


def rel(p):
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="角色扮演横评运行器")
    ap.add_argument("--adapter", required=True, help="适配器名（adapters/<name>/run.py）或脚本路径")
    ap.add_argument("--profiles", default="P0,P1,P2,P3,P4")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    ap.add_argument("--raw-dir", default=str(ROOT / "raw"))
    args = ap.parse_args(argv)

    label, cmd = adapter_cmd(args.adapter)
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    data_dir = Path(args.data)
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    raw_dir = Path(args.raw_dir)
    if not raw_dir.is_absolute():
        raw_dir = ROOT / raw_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    summary = {"adapter": label, "command": [rel(x) if x.endswith(".py") else x for x in cmd],
               "data": rel(data_dir), "profiles": {}, "determinism": {},
               "timing_policy": {"warmup": WARMUP, "samples": SAMPLES,
                                 "scope": "process-start-to-exit-full-6-turns"}}
    repeat_lines = ["# adapter=%s warmup=%d samples=%d" % (label, WARMUP, SAMPLES)]
    failures = 0

    for profile in profiles:
        out_path = out_dir / ("%s_%s.json" % (label, profile))
        runs = []
        for _ in range(WARMUP + SAMPLES):
            proc, ms = invoke(cmd, data_dir, profile, out_path)
            runs.append({"ms": ms, "rc": proc.returncode,
                         "stdout": proc.stdout, "stderr": proc.stderr})
        timed = runs[WARMUP:]
        samples = [r["ms"] for r in timed]
        stdout_bytes = timed[-1]["stdout"]
        text = stdout_bytes.decode("utf-8", errors="replace")

        (raw_dir / ("%s_%s.txt" % (label, profile))).write_bytes(stdout_bytes)
        if out_path.exists():
            (raw_dir / ("%s_%s.json" % (label, profile))).write_bytes(out_path.read_bytes())

        errs = []
        rc = timed[-1]["rc"]
        if rc != 0:
            errs.append("exit-%d" % rc)
        digests = {metrics.sha256_bytes(r["stdout"]) for r in runs}
        identical = len(digests) == 1
        stdout_sha = metrics.sha256_bytes(stdout_bytes)
        if not identical:
            errs.append("nondeterministic-stdout=%d" % len(digests))
        if all(r["rc"] == 0 for r in runs) is False:
            errs.append("nonzero-rc-in-repeats")

        rows, fmt_errs = parse_readouts(text)
        errs.extend(fmt_errs)
        doc = {}
        if out_path.exists():
            try:
                doc = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception as exc:
                errs.append("out-json:%s" % exc)
        else:
            errs.append("out-json-missing")
        errs.extend(cross_check(label, profile, rows, doc))

        for t in sorted(rows):
            print(rows[t]["line"])
        print(metrics.timing_line(label, profile, min(samples),
                                  metrics.percentile(samples, 0.5),
                                  metrics.percentile(samples, 0.95)))
        print(metrics.determinism_line(label, len(runs), identical, stdout_sha))
        if out_path.exists():
            print(metrics.sha_line(metrics.sha256_bytes(out_path.read_bytes()), rel(out_path)))
        for e in sorted(set(errs)):
            print(metrics.error_line(label, profile, e))
            failures += 1
        repeat_lines.append("# profile=%s" % profile)
        repeat_lines.append(metrics.determinism_line(label, len(runs), identical, stdout_sha))

        summary["profiles"][profile] = {
            "out": rel(out_path),
            "out_sha256": metrics.sha256_bytes(out_path.read_bytes()) if out_path.exists() else None,
            "stdout_sha256": stdout_sha,
            "exit_code": rc,
            "turns": [{"turn": t["turn"], "active_uids": t["active_uids"],
                       "inject_order": t["inject_order"],
                       "chars": t["totals"]["chars"], "bytes": t["totals"]["bytes"],
                       "dropped_uids": t["totals"]["dropped_uids"]}
                      for t in doc.get("turns", [])] if isinstance(doc, dict) else [],
            "capabilities": doc.get("capabilities", {}) if isinstance(doc, dict) else {},
            "unsupported": doc.get("unsupported", []) if isinstance(doc, dict) else [],
            "errors": sorted(set(errs)),
            "timing": {"warmup": WARMUP, "samples": SAMPLES,
                       "min_ms": round(min(samples), 3),
                       "p50_ms": round(metrics.percentile(samples, 0.5), 3),
                       "p95_ms": round(metrics.percentile(samples, 0.95), 3)},
            "readout_lines": [rows[t]["line"] for t in sorted(rows)],
        }
        summary["determinism"][profile] = {"repeats": len(runs), "identical": identical,
                                           "sha": stdout_sha}

    (raw_dir / ("%s_summary.json" % label)).write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    (raw_dir / ("%s_repeat.txt" % label)).write_text(
        "\n".join(repeat_lines) + "\n", encoding="utf-8", newline="\n")
    print("SUMMARY adapter=%s profiles=%d failures=%d" % (label, len(profiles), failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
