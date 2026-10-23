#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""贡献总表（按年/按月）守卫：聚合自洽 ＋ 盘上产物不陈旧。

为什么需要（本仓已发生过的失效形态）：
  生成器改了口径、或账本追加了新事件，而 docs/bounty/贡献总表.md 没重新生成时，
  盘上那份会**静默陈旧**——render 本身不红、账本不变量也不查它（I13 只查日表）。
  本守卫把「盘上 == 现算」变成可执行断言。

三条断言：
  A1 确定性：同一账本两次渲染逐字节相同。
  A2 聚合自洽：年合计 == 月合计 == 事件数；Δ 同。
  A3 盘上不陈旧：committed 的贡献总表.md 与现算结果逐字节相同。
"""

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import monthly_summary  # noqa: E402

LEDGER = os.path.join(ROOT, 'docs', 'bounty', 'ledger.json')
COMMITTED = os.path.join(ROOT, 'docs', 'bounty', '贡献总表.md')

PASS = []
FAIL = []


def check(name, ok, detail=''):
    (PASS if ok else FAIL).append((name, detail))
    print('[%s] %s%s' % ('PASS' if ok else 'FAIL', name, ('  ← ' + detail) if detail else ''))


def main():
    events = monthly_summary.load(LEDGER)

    # ---- A1 确定性 ----
    t1, n1, d1 = monthly_summary.build(events)
    t2, n2, d2 = monthly_summary.build(events)
    check('A1 同一账本两次渲染逐字节相同', t1 == t2 and (n1, d1) == (n2, d2),
          'first diff at %r' % next((i for i, (a, b) in enumerate(zip(t1, t2)) if a != b), -1))

    # ---- A2 聚合自洽 ----
    by_year, by_month, by_ym = monthly_summary.aggregate(events)
    yn = sum(x['n'] for x in by_year.values())
    mn = sum(x['n'] for x in by_month.values())
    yd = sum(x['delta'] for x in by_year.values())
    md = sum(x['delta'] for x in by_month.values())
    check('A2 年/月/事件数三路一致', yn == mn == len(events) == n1,
          'year=%d month=%d events=%d header=%d' % (yn, mn, len(events), n1))
    check('A2b 年/月 Δ 三路一致', yd == md == d1,
          'year=%d month=%d header=%d' % (yd, md, d1))

    # ---- A3 盘上不陈旧 ----
    if not os.path.isfile(COMMITTED):
        check('A3 盘上产物存在', False, '缺 %s' % COMMITTED)
    else:
        with io.open(COMMITTED, encoding='utf-8') as f:
            disk = f.read().replace('\r\n', '\n')
        check('A3 盘上产物 == 现算（不陈旧）', disk == t1,
              '重跑 scripts/monthly_summary.py --out docs/bounty/贡献总表.md')

    print()
    print('通过 %d / 失败 %d' % (len(PASS), len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())