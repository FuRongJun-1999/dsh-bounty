# -*- coding: utf-8 -*-
"""game.run —— 命令行入口：`python -X utf8 game/run.py --demo`。

子命令/选项：
  --demo            跑一段完整回合（起 → 行动 → 结算 → 落痕）并打印，退出码 0
  --seed N          确定性地选择剧本（N % 剧本数），选取结果写入落痕
  --name NAME       角色名（默认「旅人」）
  --list            列出全部剧本（名字 + 步数）
  --digest          只打印落痕摘要（供逐字节比对；同种子必须完全相同）
  --help
退出码：0 = 正常；1 = 运行期判据被违反（StateError / MemoryConflict）；2 = 用法错误。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.engine import SCENARIOS, pick_scenario, run_round          # noqa: E402
from game.memory import MemoryConflict                              # noqa: E402
from game.rules import StateError                                   # noqa: E402

USAGE = __doc__


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or "--help" in args or "-h" in args:
        print(USAGE)
        return 0 if args else 2

    seed = 0
    name = "旅人"
    if "--seed" in args:
        i = args.index("--seed")
        if i + 1 >= len(args):
            print("用法错误：--seed 需要一个整数", file=sys.stderr)
            return 2
        try:
            seed = int(args[i + 1])
        except ValueError:
            print(f"用法错误：--seed 需要整数，得到 {args[i+1]!r}", file=sys.stderr)
            return 2
    if "--name" in args:
        i = args.index("--name")
        if i + 1 >= len(args):
            print("用法错误：--name 需要一个值", file=sys.stderr)
            return 2
        name = args[i + 1]

    if "--list" in args:
        for idx, (sc, steps) in enumerate(SCENARIOS):
            print(f"  [{idx}] {sc}  （{len(steps)} 步）")
        return 0

    if "--demo" not in args and "--digest" not in args:
        print(USAGE)
        return 2

    try:
        log, ch, mem = run_round(name=name, seed=seed)
    except (StateError, MemoryConflict) as exc:
        print(f"运行期判据被违反：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if "--digest" in args:
        print(repr(log.digest()))
        return 0

    sc, steps = pick_scenario(seed)
    print(f"=== 角色扮演 · 一段完整回合（剧本『{sc}』）===")
    print()
    for ln in log.lines:
        print("  " + ln)
    print()
    print(f"  — 回合结束：{ch.name} 状态『{ch.state}』，生命值 {ch.hp}，"
          f"记忆 {len(mem.trace())} 条")
    print(f"  — 落痕摘要：{log.digest()!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
