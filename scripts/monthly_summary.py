#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵枢悬赏板 · 贡献总表（按年 / 按月）生成器。

从 docs/bounty/ledger.json（append-only 事件流）机械生成 docs/bounty/贡献总表.md。

口径：
  - 只做聚合，不重算 Δ —— Δ 的定档与公式见 bounty_board.quality_delta，本脚本只求和。
  - 归组键取事件的 day 字段（结算日，UTC+8）。
  - 自检：年合计、月合计、总计三者必须相等，否则非零退出。

用法：
  python -X utf8 scripts/monthly_summary.py --ledger docs/bounty/ledger.json --out docs/bounty/贡献总表.md
  python -X utf8 scripts/monthly_summary.py --check     # 只校验，不写文件
"""

import argparse
import collections
import io
import json
import os
import sys


def load(ledger_path):
    with io.open(ledger_path, encoding='utf-8') as f:
        led = json.load(f)
    events = led.get('events') or []
    if not isinstance(events, list):
        raise SystemExit('账本 events 不是数组')
    return events


def aggregate(events):
    """按年、按月、按年月的三重聚合。"""
    by_year = collections.OrderedDict()
    by_month = collections.OrderedDict()
    by_ym = collections.OrderedDict()

    for e in events:
        day = e.get('day') or ''
        if len(day) < 10:
            raise SystemExit('事件 day 非法：%r（issue=%r）' % (day, e.get('issue')))
        y, m, ym = day[:4], day[:7], day[:7]
        delta = int(e.get('delta') or 0)
        holder = e.get('holder') or ''
        project = e.get('project') or ''
        for bucket, key in ((by_year, y), (by_month, ym), (by_ym, ym)):
            d = bucket.setdefault(key, {'n': 0, 'delta': 0,
                                        'holders': set(), 'projects': set(), 'days': set()})
            d['n'] += 1
            d['delta'] += delta
            d['holders'].add(holder)
            d['projects'].add(project)
            d['days'].add(day)

    return by_year, by_month, by_ym


def _span(days, lo, hi):
    """区间跨度：lo/hi 是切片下标。单值只返回该值，多值返回 起-止。"""
    vals = sorted({x[lo:hi] for x in days})
    return vals[0] if len(vals) == 1 else '%s-%s' % (vals[0], vals[-1])


def fmt_row(key, d, span_kind='day'):
    days = sorted(d['days'])
    if span_kind == 'month':
        span = _span(days, 5, 7)      # YYYY-MM-DD -> MM
    else:
        span = _span(days, 8, 10)     # YYYY-MM-DD -> DD
    return '| %s | %d | **%d** | %d | %d | %d | %s |' % (
        key, d['n'], d['delta'], len(d['holders']), len(d['projects']), len(d['days']), span)


def build(events):
    by_year, by_month, by_ym = aggregate(events)
    total_n = sum(d['n'] for d in by_year.values())
    total_delta = sum(d['delta'] for d in by_year.values())
    all_days = sorted({e.get('day') for e in events})

    # ---- 自检：三条路径的合计必须一致 ----
    assert total_n == sum(d['n'] for d in by_month.values()) == len(events), '月合计与事件数不符'
    assert total_delta == sum(d['delta'] for d in by_month.values()), '月 Δ 合计不符'
    if by_ym:
        assert total_n == sum(d['n'] for d in by_ym.values()), '年月合计不符'

    L = []
    L.append('# 灵枢悬赏板 · 贡献总表')
    L.append('')
    L.append('> 本页由 `scripts/monthly_summary.py` 从 `docs/bounty/ledger.json`（append-only 事件流）**机械生成**——勿手改，手改会在下一次生成时被覆盖。')
    L.append('> 账本事件数：%d ｜ Δ 合计：%d ｜ 结算日：%d ｜ 区间：%s ~ %s'
             % (total_n, total_delta, len(all_days), all_days[0], all_days[-1]))
    L.append('')
    L.append('> 计分口径：Δ = max(1, round_half_up(base × 2 / (r + 1)))，r = max(0, rounds - 1)。'
             '本表只做聚合，不重算 Δ；定档依据与复现读数见对应 issue / PR 与 `ledger.json`。')
    L.append('')
    L.append('> 本站只做声誉分与价值评价；金额不进站。两轴（难度 / 影响等级）分别记录，合成权重与资金换算属使用者侧。')
    L.append('')

    # ---- 按年总计 ----
    L.append('## 按年总计')
    L.append('')
    L.append('| 年份 | 结算项 | Δ 合计 | 贡献者 | 项目 | 活跃天数 | 月份跨度 |')
    L.append('|---|---|---|---|---|---|---|')
    for y in sorted(by_year):
        L.append(fmt_row(y, by_year[y], span_kind='month'))
    L.append('| **合计** | **%d** | **%d** | %d | %d | %d | — |'
             % (total_n, total_delta,
                len({e.get('holder') for e in events}),
                len({e.get('project') for e in events}),
                len(all_days)))
    L.append('')

    # ---- 按月总计 ----
    L.append('## 按月总计')
    L.append('')
    L.append('| 年月 | 结算项 | Δ 合计 | 贡献者 | 项目 | 活跃天数 | 日跨度 |')
    L.append('|---|---|---|---|---|---|---|')
    for ym in sorted(by_month):
        L.append(fmt_row(ym, by_month[ym]))
    L.append('| **合计** | **%d** | **%d** | %d | %d | %d | — |'
             % (total_n, total_delta,
                len({e.get('holder') for e in events}),
                len({e.get('project') for e in events}),
                len(all_days)))
    L.append('')

    # ---- 月度趋势（纯文本条） ----
    L.append('## 月度趋势')
    L.append('')
    L.append('条长按 Δ 相对最大值缩放，每格 = 最大月的 1/20。')
    L.append('')
    L.append('```')
    max_d = max((d['delta'] for d in by_month.values()), default=1) or 1
    for ym in sorted(by_month):
        d = by_month[ym]
        bar = '#' * max(1, round(d['delta'] / max_d * 20))
        L.append('%s  %-20s %5d  (%d 项)' % (ym, bar, d['delta'], d['n']))
    L.append('```')
    L.append('')
    L.append('---')
    L.append('')
    L.append('生成命令：')
    L.append('')
    L.append('```')
    L.append('python -X utf8 scripts/monthly_summary.py --ledger docs/bounty/ledger.json --out docs/bounty/贡献总表.md')
    L.append('```')
    L.append('')
    return '\n'.join(L), total_n, total_delta


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--ledger', default='docs/bounty/ledger.json')
    ap.add_argument('--out', default='docs/bounty/贡献总表.md')
    ap.add_argument('--check', action='store_true', help='只校验聚合自洽，不写文件')
    args = ap.parse_args(argv)

    events = load(args.ledger)
    text, n, delta = build(events)

    if args.check:
        print('[OK] %d 项 / Δ%d 聚合自洽' % (n, delta))
        return 0

    d = os.path.dirname(args.out)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print('[OK] %s ← %d 项 / Δ%d' % (args.out, n, delta))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))