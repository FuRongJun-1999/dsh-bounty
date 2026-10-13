# -*- coding: utf-8 -*-
"""历史快照补录（**手动一次性**）：把 10-11 与 10-12 两天的得分落进 contrib_snapshot。

口径（2026-10-13 与使用者确认）：
  * 这两版是**初期运行的 bootstrap 数据**（机器人上线前就存在），
    各按**自身累计**记：11 号 = v0.1 表累计（62 分 / 9 人），12 号 = 新贡献表累计（95 分 / 7 人）；
  * 常态口径 = **今天累计 − 昨天累计**（相邻两版快照求差）；
  * 11、12 是**两套不同算法**，不可相减 => 12 号整份记为新基线，从 13 号起按新表正常求差。

用法：
    python3 backfill.py --dry-run          # 只看会写什么
    python3 backfill.py                    # 真写
    python3 backfill.py --table <贡献表.md> --v01 <v0.1.md>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db        # noqa: E402
import settle    # noqa: E402

#: 补录日期与来源（表里没有日期，由这里的登记确定）
DAY_V01 = "2026-10-11"
DAY_LEDGER = "2026-10-12"
SRC_V01 = "v0.1"
SRC_LEDGER = "ledger"


def _parse(path):
    text = Path(path).read_text(encoding="utf-8")
    _issues, totals = settle.parse(text)
    return text, totals


def _day_of(text, fallback_pairs):
    """优先用表里写明的结算日；取不到则用登记日期。"""
    return settle.day_of(text), fallback_pairs


def main(argv=None):
    ap = argparse.ArgumentParser(description="补录 10-11 / 10-12 历史快照")
    ap.add_argument("--db", default=str(Path(__file__).resolve().parent / "bounty.db"))
    ap.add_argument("--table", default="docs/bounty/贡献表.md",
                    help="10-12 的新贡献表（可给本地路径）")
    ap.add_argument("--v01", default="docs/spec/贡献结算表_v0.1.md",
                    help="10-11 的 v0.1 老表")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    ok = True
    plan = []
    for label, path, day, src in (("v0.1 老表", args.v01, DAY_V01, SRC_V01),
                                  ("新贡献表", args.table, DAY_LEDGER, SRC_LEDGER)):
        p = Path(path)
        if not p.exists():
            print("  SKIP  %s 不存在：%s" % (label, path))
            ok = False
            continue
        text, totals = _parse(p)
        pairs = [(t["github"], int(t["total"])) for t in totals]
        total = sum(v for _g, v in pairs)
        print("  %-10s %s -> %s  %d 人 / %d 分" % (label, p.name, day, len(pairs), total))
        plan.append((day, pairs, src))

    if not plan:
        print("没有可补录的数据")
        return 2
    if args.dry_run:
        print("  --dry-run：不写库")
        return 0

    conn = db.connect(args.db)
    for day, pairs, src in plan:
        n = db.seed_snapshot(conn, day, pairs, src=src)
        print("  写入 %s：%d 行 (src=%s)" % (day, n, src))
    conn.close()
    print("完成。" if ok else "完成（有跳过项）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
