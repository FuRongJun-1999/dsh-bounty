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

    # ---- A7 空账本：合法状态，不崩、合计 0（与 check_ledger_invariants A6 同口径） ----
    try:
        t0, n0, d0 = monthly_summary.build([])
        empty_ok = (n0 == 0 and d0 == 0 and '账本为空' in t0)
        empty_detail = 'n=%r d=%r has_note=%r' % (n0, d0, '账本为空' in t0)
    except Exception as ex:  # noqa: BLE001 —— 守卫要把它变成可点名的 FAIL，而不是让整条腿裸栈
        empty_ok = False
        empty_detail = '%s: %s' % (type(ex).__name__, ex)
    check('A7 空账本：不崩、合计 0、明说「账本为空」', empty_ok, empty_detail)

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
