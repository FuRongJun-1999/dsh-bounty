#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""贡献总表守卫：聚合自洽（含贡献者维度）＋ 盘上产物不陈旧。

为什么需要（本仓已发生过的失效形态）：
  生成器改了口径、或账本追加了新事件，而 docs/bounty/贡献总表.md 没重新生成时，
  盘上那份会**静默陈旧** —— render 本身不红、账本不变量也不查它（I13 只查日表）。
  本守卫把「盘上 == 现算」变成可执行断言。

断言：
  A1  确定性：同一账本两次渲染逐字节相同。
  A2  年 / 月 / 事件数 三路一致。
  A2b Δ 三路一致。
  A2c 贡献者合计 == 总计（新增维度，防「按人聚合漏项」）。
  A2d 贡献者×月 合计 == 总计（月度结算主表的口径）。
  A2e 贡献者×年 合计 == 总计。
  A3  盘上不陈旧：committed 的贡献总表.md 与现算结果逐字节相同。
"""

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import monthly_summary  # noqa: E402

LEDGER = os.path.join(ROOT, 'docs', 'bounty', 'ledger.json')
COMMITTED = os.path.join(ROOT, 'docs', 'bounty', '贡献总表.md')

PASSED = []
FAILED = []


def check(name, ok, detail=''):
    (PASSED if ok else FAILED).append((name, detail))
    print('[%s] %s%s' % ('PASS' if ok else 'FAIL', name, ('  <- ' + detail) if detail else ''))


def main():
    events = monthly_summary.load(LEDGER)

    # ---- A1 确定性 ----
    t1, n1, d1 = monthly_summary.build(events)
    t2, n2, d2 = monthly_summary.build(events)
    check('A1 同一账本两次渲染逐字节相同', t1 == t2 and (n1, d1) == (n2, d2),
          'first diff at %r' % next((i for i, (a, b) in enumerate(zip(t1, t2)) if a != b), -1))

    # ---- A2 聚合自洽 ----
    by_year, by_month, by_holder, hm, hy, _hd, _hp = monthly_summary.aggregate(events)
    yn = sum(x['n'] for x in by_year.values())
    mn = sum(x['n'] for x in by_month.values())
    yd = sum(x['delta'] for x in by_year.values())
    md = sum(x['delta'] for x in by_month.values())
    hd = sum(x['delta'] for x in by_holder.values())
    hm_d = sum(sum(v.values()) for v in hm.values())
    hy_d = sum(sum(v.values()) for v in hy.values())

    check('A2 年/月/事件数三路一致', yn == mn == len(events) == n1,
          'year=%d month=%d events=%d header=%d' % (yn, mn, len(events), n1))
    check('A2b 年/月 Δ 三路一致', yd == md == d1,
          'year=%d month=%d header=%d' % (yd, md, d1))
    check('A2c 贡献者 Δ 合计 == 总计', hd == d1, 'holders=%d header=%d' % (hd, d1))
    check('A2d 贡献者x月 Δ 合计 == 总计', hm_d == d1, 'hm=%d header=%d' % (hm_d, d1))
    check('A2e 贡献者x年 Δ 合计 == 总计', hy_d == d1, 'hy=%d header=%d' % (hy_d, d1))

    # 贡献者逐人：其各月之和 == 其年之和 == 其总计
    bad = []
    for h, d in by_holder.items():
        if sum(hm[h].values()) != d['delta'] or sum(hy[h].values()) != d['delta']:
            bad.append(h)
    check('A2f 每个贡献者月/年/总计自洽', not bad, 'mismatch=%r' % bad[:5])

    # ---- A4 当月明细表自洽（跨月才暴露：三列必须是「当月」口径，不是全生命周期） ----
    two = [
        {"issue": 1, "day": "2026-10-03", "delta": 3, "holder": "alice", "project": "mem",  "difficulty": "medium"},
        {"issue": 2, "day": "2026-10-05", "delta": 3, "holder": "alice", "project": "mem",  "difficulty": "medium"},
        {"issue": 3, "day": "2026-10-07", "delta": 1, "holder": "bob",   "project": "site", "difficulty": "easy"},
        {"issue": 4, "day": "2026-11-02", "delta": 6, "holder": "alice", "project": "mem",  "difficulty": "hard"},
    ]
    t2s, _, _ = monthly_summary.build(two)
    blk = t2s.split('## 当月结算明细')[1].split('## 月度趋势')[0]
    rows = [l for l in blk.splitlines() if l.startswith('| ') and '@' in l]
    tot = [l for l in blk.splitlines() if l.startswith('| ') and '合计' in l][0]

    def cells(r):
        return [c.strip().strip('*') for c in r.strip().strip('|').split('|')]

    data = [cells(r) for r in rows]
    total = cells(tot)
    sum_n = sum(int(c[3]) for c in data)
    sum_diff = [sum(int(c[i]) for c in data) for i in (4, 5, 6, 7)]
    check('A4 当月明细：每人行「结算项」之和 == 合计行 == 当月事件数',
          sum_n == int(total[3]) == 1, 'rows=%d total=%s' % (sum_n, total[3]))
    check('A4b 当月明细：难度列每人之和 == 合计行（当月口径，不含他月）',
          sum_diff == [int(total[i]) for i in (4, 5, 6, 7)] == [0, 0, 1, 0],
          'rows=%r total=%r' % (sum_diff, [total[i] for i in (4, 5, 6, 7)]))
    check('A4c 当月明细：项目分布 = 当月 Δ（不是全期 Δ）',
          data[0][8] == 'mem 6', 'alice=%r' % data[0][8])

    # ---- A3 盘上不陈旧 ----
    if not os.path.isfile(COMMITTED):
        check('A3 盘上产物存在', False, '缺 %s' % COMMITTED)
    else:
        with io.open(COMMITTED, encoding='utf-8') as f:
            disk = f.read().replace('\r\n', '\n')
        check('A3 盘上产物 == 现算（不陈旧）', disk == t1,
              '重跑 scripts/monthly_summary.py --out docs/bounty/贡献总表.md')

    print()
    print('通过 %d / 失败 %d' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
