#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量定点变异自证：把「自己实现了 --mutate 的守卫」逐件真跑一遍。

为什么需要这个文件（2026-10-14 立）：
  `bounty-board-check.yml` 原本只对 `tests/test_bounty_board.py` 一件跑 `--mutate`（第 2 步），
  而本仓另有 **16 件守卫自带 `--mutate`**（正反两模式），此前没有任何 workflow 会跑它们
  —— 又是「有人写了、没人跑」。代价不是「少跑一次」，而是**反面证明会静默腐朽**：
  变异锚点按源码文本定位，实现一改（例如判据从串联改并联）锚点就打不中，而打不中时
  harness 只会自己 fail-closed 报 `[ANCHOR-MISS]` —— **没人跑就没人知道**。
  实证：#383（`test_check_plan.py --mutate` 的 7 条锚点里 2 条已是旧快照，主线上一跑即 rc=2）。

判据（fail-closed，三处都不许静默）：
  1) 参检件数不得少于 FLOOR —— 防「删掉/改名一批 harness」让本步静默变松；
  2) `SPECIAL_ARGS` 的每条都必须仍在参检集合内 —— 防陈旧特例表；
  3) 每件必须 rc=0；出现 `ANCHOR-MISS` 或其它非零 ⇒ 逐件点名并退 1。
  特例表只用于「需要取值的 harness」（`--mutate=<id>`），**不是**为了跳过任何文件。

零第三方依赖、不触网；跑完不留残留（由 workflow 第 4 步「跑完不许把仓搞脏」兜底）。
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
FLOOR = 16          # 2026-10-15 实测 17 件；下界留 1 件余量——「一批删除/改名」即红，单件合并不误伤
TIMEOUT_S = 300     # 单件上限（实测最慢一件 42s，CI 上留足余量）
SPECIAL_ARGS = {    # 需要显式取值的 harness
    "test_check_reviews_roleplay.py": ["--mutate=R8b"],   # 该件 --mutate 需取值；R8b 为其文档示例
}
MISS_RE = re.compile(r"ANCHOR-MISS")


def discover():
    out = []
    for p in sorted(HERE.glob("test_*.py")):
        try:
            if "--mutate" in p.read_text(encoding="utf-8"):
                out.append(p)
        except OSError:
            continue
    return out


def main() -> int:
    files = discover()
    names = {p.name for p in files}
    print("变异自证：参检 %d 件（下界 %d）" % (len(files), FLOOR))
    for n in sorted(names):
        print("  · %s" % n)

    if len(files) < FLOOR:
        print("::error::参检件数从 %d 降到 %d —— 是否删了/改名了带 --mutate 的守卫？" % (FLOOR, len(files)))
        return 1
    stale = sorted(set(SPECIAL_ARGS) - names)
    if stale:
        print("::error::SPECIAL_ARGS 特例表过期：%s 已不在参检集合内" % ", ".join(stale))
        return 1

    passed = 0
    failed = 0
    for p in files:
        args = SPECIAL_ARGS.get(p.name, ["--mutate"])
        cmd = [sys.executable, "-X", "utf8", str(p), *args]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  cwd=str(ROOT), timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            print("[TIMEOUT] %s（>%ds）" % (p.name, TIMEOUT_S))
            failed += 1
            continue
        blob = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0:
            print("[OK]      %s  %s" % (p.name, args[-1]))
            passed += 1
            continue
        failed += 1
        why = "ANCHOR-MISS" if MISS_RE.search(blob) else "rc=%d" % proc.returncode
        print("[FAIL]    %s  (%s)" % (p.name, why))
        for line in [l for l in blob.splitlines() if l.strip()][-3:]:
            print("            %s" % line[:160])

    print("变异守卫：执行 %d 件 · 通过 %d · 失败 %d" % (len(files), passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
