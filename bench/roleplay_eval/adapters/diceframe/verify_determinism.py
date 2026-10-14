#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同输入连跑 N 次的确定性核对：比对 adapter stdout 与 out JSON 的 sha256。

用法（仓库内脚本只用标准库）：
  <venv python> -X utf8 adapters/diceframe/verify_determinism.py [--repeats 5]

产物：raw/diceframe_determinism.txt（SHA 行 + DETERMINISM 行，行语法见 CONTRACT 7.2）。
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent.parent                      # bench/roleplay_eval
sys.path.insert(0, str(EVAL / "harness"))

import metrics  # noqa: E402

NAME = "diceframe"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description="diceframe 确定性核对")
    ap.add_argument("--profiles", default="P0,P1,P2,P3,P4")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--out", default=str(EVAL / "raw" / (NAME + "_determinism.txt")))
    args = ap.parse_args(argv)

    lines = ["# adapter=%s repeats=%d scopes=stdout+out" % (NAME, args.repeats)]
    failures = 0
    for profile in [p.strip() for p in args.profiles.split(",") if p.strip()]:
        out_path = EVAL / "out" / ("%s_%s.json" % (NAME, profile))
        digests: list[str] = []
        for index in range(args.repeats):
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", str(HERE / "run.py"),
                 "--data", str(EVAL / "data"), "--profile", profile,
                 "--out", str(out_path)],
                capture_output=True)
            if proc.returncode != 0:
                failures += 1
                lines.append(metrics.error_line(NAME, profile, "exit-%d" % proc.returncode))
            digests.append(hashlib.sha256(proc.stdout).hexdigest())
            lines.append(metrics.sha_line(sha256_file(out_path),
                                          "out/%s_%s.json" % (NAME, profile)))
        identical = len(set(digests)) == 1 and failures == 0
        if not identical:
            failures += 1
        lines.append("# profile=%s stdout_sha256_each_run=%s" % (profile, ",".join(digests)))
        lines.append(metrics.determinism_line(NAME, args.repeats, identical, digests[-1]))
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    for line in lines:
        print(line)
    print("SUMMARY adapter=%s repeats=%d failures=%d" % (NAME, args.repeats, failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
