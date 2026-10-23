#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵枢悬赏板 · 贡献总表（按年 / 按月 / 按贡献者）生成器。

从 docs/bounty/ledger.json（append-only 事件流）机械生成 docs/bounty/贡献总表.md。

用途：月度结算 —— 表要能直接回答「某月某人拿了多少分」。

口径：
  - 只做聚合，不重算 Δ —— Δ 的定档与公式见 bounty_board.quality_delta，本脚本只求和。
  - 归组键取事件的 day 字段（结算日，UTC+8）。
  - 自检：年合计、月合计、贡献者合计、总计四路必须相等，否则非零退出。

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
    # 路径不存在 / 不是合法 JSON：兄弟闸（check_ledger_invariants、daily_table）都点名 + 非零退出；
    # 这里原先直接裸栈（FileNotFoundError / JSONDecodeError），看不出是哪一种坏法。
    if not os.path.isfile(ledger_path):
        raise SystemExit('::error::账本不存在：%s（检查 --ledger 路径）' % ledger_path)
    try:
        with io.open(ledger_path, encoding='utf-8') as f:
            led = json.load(f)
    except ValueError as exc:
        raise SystemExit('::error::账本不是合法 JSON：%s（%s）' % (ledger_path, exc))
    events = led.get('events') or []
    if not isinstance(events, list):
        raise SystemExit('::error::账本 events 不是数组：%s（实际 %s）'
                         % (ledger_path, type(events).__name__))
    return events


def _blank():
    return {'n': 0, 'delta': 0, 'holders': set(), 'projects': set(), 'days': set()}


def aggregate(events):
    by_year, by_month = collections.OrderedDict(), collections.OrderedDict()
    by_holder = collections.OrderedDict()
    hm = collections.defaultdict(lambda: collections.OrderedDict())
    hy = collections.defaultdict(lambda: collections.OrderedDict())
    hdiff = collections.defaultdict(lambda: collections.Counter())
    hproj = collections.defaultdict(lambda: collections.Counter())

    for e in events:
        day = e.get('day') or ''
        if len(day) < 10:
            raise SystemExit('事件 day 非法：%r（issue=%r）' % (day, e.get('issue')))
        y, ym = day[:4], day[:7]
        delta = int(e.get('delta') or 0)
        holder = e.get('holder') or '(unknown)'
        project = e.get('project') or '(unknown)'

        for bucket, key in ((by_year, y), (by_month, ym), (by_holder, holder)):
            d = bucket.setdefault(key, _blank())
            d['n'] += 1
            d['delta'] += delta
            d['holders'].add(holder)
            d['projects'].add(project)
            d['days'].add(day)

        hm[holder][ym] = hm[holder].get(ym, 0) + delta
        hy[holder][y] = hy[holder].get(y, 0) + delta
        hdiff[holder][e.get('difficulty') or '?'] += 1
        hproj[holder][project] += delta

    return by_year, by_month, by_holder, hm, hy, hdiff, hproj


def _span(days, lo, hi):
    vals = sorted({x[lo:hi] for x in days})
    return vals[0] if len(vals) == 1 else '%s-%s' % (vals[0], vals[-1])


def fmt_row(key, d, span_kind='day'):
    days = sorted(d['days'])
    span = _span(days, 5, 7) if span_kind == 'month' else _span(days, 8, 10)
    return '| %s | %d | **%d** | %d | %d | %d | %s |' % (
        key, d['n'], d['delta'], len(d['holders']), len(d['projects']), len(d['days']), span)


def _proj_brief(counter, top=3):
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return ' / '.join('%s %d' % (k, v) for k, v in items)

def build(events):
    by_year, by_month, by_holder, hm, hy, hdiff, hproj = aggregate(events)
    total_n = sum(d['n'] for d in by_year.values())
    total_delta = sum(d['delta'] for d in by_year.values())
    all_days = sorted({e.get('day') for e in events})
    months = sorted(by_month)
    years = sorted(by_year)
    holders = sorted(by_holder, key=lambda h: (-by_holder[h]['delta'], h))
    n_proj = len({e.get('project') for e in events})

    assert total_n == len(events), '年合计与事件数不符'
    assert total_delta == sum(d['delta'] for d in by_month.values()), '月 Δ 合计不符'
    assert total_delta == sum(d['delta'] for d in by_holder.values()), '贡献者 Δ 合计不符'
    assert total_delta == sum(sum(v.values()) for v in hm.values()), '贡献者x月 Δ 合计不符'
    assert total_delta == sum(sum(v.values()) for v in hy.values()), '贡献者x年 Δ 合计不符'

    L = []
    add = L.append
    add('# 灵枢悬赏板 · 贡献总表')
    add('')
    add('> 本页由 `scripts/monthly_summary.py` 从 `docs/bounty/ledger.json`（append-only 事件流）**机械生成**——勿手改，手改会在下一次生成时被覆盖。')
    add('> 账本事件数：%d ｜ Δ 合计：%d ｜ 贡献者：%d ｜ 项目：%d ｜ 结算日：%d ｜ 区间：%s ~ %s'
        % (total_n, total_delta, len(by_holder), n_proj, len(all_days), all_days[0], all_days[-1]))
    add('')
    add('> 计分口径：Δ = max(1, round_half_up(base × 2 / (r + 1)))，r = max(0, rounds - 1)。本表只做聚合，不重算 Δ；定档依据与复现读数见对应 issue / PR 与 `ledger.json`。')
    add('')
    add('> **月度结算用法**：看「按月 × 贡献者」表，某列 = 某月应付给各贡献者的分；「当月结算明细」给出该月每人的难度与项目分布，便于逐人核对。')
    add('')
    add('> 本站只做声誉分与价值评价；金额不进站。两轴（难度 / 影响等级）分别记录，合成权重与资金换算属使用者侧。')
    add('')

    add('## 全站按年总计')
    add('')
    add('| 年份 | 结算项 | Δ 合计 | 贡献者 | 项目 | 活跃天数 | 月份跨度 |')
    add('|---|---|---|---|---|---|---|')
    for y in years:
        add(fmt_row(y, by_year[y], span_kind='month'))
    add('| **合计** | **%d** | **%d** | %d | %d | %d | — |' % (total_n, total_delta, len(by_holder), n_proj, len(all_days)))
    add('')

    add('## 全站按月总计')
    add('')
    add('| 年月 | 结算项 | Δ 合计 | 贡献者 | 项目 | 活跃天数 | 日跨度 |')
    add('|---|---|---|---|---|---|---|')
    for ym in months:
        add(fmt_row(ym, by_month[ym]))
    add('| **合计** | **%d** | **%d** | %d | %d | %d | — |' % (total_n, total_delta, len(by_holder), n_proj, len(all_days)))
    add('')

    add('## 按年 × 贡献者（Δ）')
    add('')
    add('行按合计降序；列 = 各年。')
    add('')
    add('| 贡献者 | ' + ' | '.join(years) + ' | **合计** | 结算项 |')
    add('|---|' + '---|' * len(years) + '---|---|')
    for h in holders:
        cells = ' | '.join(str(hy[h][y]) if hy[h].get(y) else '·' for y in years)
        add('| @%s | %s | **%d** | %d |' % (h, cells, by_holder[h]['delta'], by_holder[h]['n']))
    add('| **合计** | ' + ' | '.join('**%d**' % by_year[y]['delta'] for y in years) + ' | **%d** | **%d** |' % (total_delta, total_n))
    add('')

    add('## 按月 × 贡献者（Δ）—— **月度结算主表**')
    add('')
    add('行按合计降序；列 = 各月。**某列之和 = 该月应付总额**。')
    add('')
    add('| 贡献者 | ' + ' | '.join(months) + ' | **合计** | 结算项 |')
    add('|---|' + '---|' * len(months) + '---|---|')
    for h in holders:
        cells = ' | '.join(str(hm[h][ym]) if hm[h].get(ym) else '·' for ym in months)
        add('| @%s | %s | **%d** | %d |' % (h, cells, by_holder[h]['delta'], by_holder[h]['n']))
    add('| **合计** | ' + ' | '.join('**%d**' % by_month[ym]['delta'] for ym in months) + ' | **%d** | **%d** |' % (total_delta, total_n))
    add('')
    latest = months[-1]
    add('## 当月结算明细 · %s' % latest)
    add('')
    add('用于当月结付核对：每人一行，含难度分布与项目分布。')
    add('')
    add('| # | 贡献者 | Δ | 结算项 | easy | medium | hard | expert | 项目分布 |')
    add('|---|---|---|---|---|---|---|---|---|')
    in_month = [h for h in holders if hm[h].get(latest)]
    in_month.sort(key=lambda h: (-hm[h][latest], h))
    for i, h in enumerate(in_month, 1):
        d = hdiff[h]
        add('| %d | @%s | **%d** | %d | %d | %d | %d | %d | %s |' % (
            i, h, hm[h][latest], by_holder[h]['n'],
            d.get('easy', 0), d.get('medium', 0), d.get('hard', 0), d.get('expert', 0),
            _proj_brief(hproj[h])))
    add('| — | **合计** | **%d** | **%d** | %d | %d | %d | %d | — |' % (
        by_month[latest]['delta'], by_month[latest]['n'],
        sum(hdiff[h].get('easy', 0) for h in in_month),
        sum(hdiff[h].get('medium', 0) for h in in_month),
        sum(hdiff[h].get('hard', 0) for h in in_month),
        sum(hdiff[h].get('expert', 0) for h in in_month)))
    add('')

    add('## 月度趋势')
    add('')
    add('条长按 Δ 相对最大值缩放，满格 = 最大月。')
    add('')
    add('```')
    max_d = max((d['delta'] for d in by_month.values()), default=1) or 1
    for ym in months:
        d = by_month[ym]
        add('%s  %-20s %6d  (%d 项 / %d 人)' % (
            ym, '#' * max(1, round(d['delta'] / max_d * 20)), d['delta'], d['n'], len(d['holders'])))
    add('```')
    add('')
    add('---')
    add('')
    add('生成命令：')
    add('')
    add('```')
    add('python -X utf8 scripts/monthly_summary.py --ledger docs/bounty/ledger.json --out docs/bounty/贡献总表.md')
    add('```')
    add('')
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
        print('[OK] %d 项 / Δ%d 四路聚合自洽' % (n, delta))
        return 0

    d = os.path.dirname(args.out)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print('[OK] %s <- %d 项 / Δ%d' % (args.out, n, delta))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
