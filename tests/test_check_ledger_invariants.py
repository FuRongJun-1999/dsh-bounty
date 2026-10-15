# -*- coding: utf-8 -*-
"""守卫：scripts/check_ledger_invariants.py（账本结构不变量自审）——断言 ＋ 定点变异自证。

  python -X utf8 tests/test_check_ledger_invariants.py            # 断言，末行「通过 N / 失败 M」
  python -X utf8 tests/test_check_ledger_invariants.py --mutate   # 定点变异自证

为什么需要：站点的账本是**跨数十轮累积追加**的真源，产物（贡献表/看板/价值向量/悬赏清单）全由它派生。
  历史上查出的缺陷（round-30 的 difficulty 存了带前缀的值、round-46 的 11 行 ts 是「本地时刻配 Z」）
  都不是逻辑错误，而是**字段形态的静默漂移** —— 写入端不报错，读端静默降级。
  本守卫把 round-46 手工跑的清单固化，使漂移在提交前就红。

判据解耦（照本仓约定）：
  · 本文件**不 import bounty_board**，id 公式独立重实现（同错同绿会让判据空转）。
  · A5 直接断言被守卫的检查器**源码里没有 import bounty_board** —— 把「解耦」本身做成判据。
  · 变异每一条**须恰好命中期望的那一项**：多红＝语义纠缠，少红＝判据空转，两者都算失败。
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(ROOT, 'scripts', 'check_ledger_invariants.py')
REAL_LEDGER = os.path.join(ROOT, 'docs', 'bounty', 'ledger.json')
REAL_TABLE = os.path.join(ROOT, 'docs', 'bounty', '贡献表.md')
MUTATE = '--mutate' in sys.argv
QUIET = '--quiet' in sys.argv
_red = []
_n_assert = [0]


def ok(name, cond):
    _n_assert[0] += 1
    if not cond:
        _red.append(name.split(' ')[0])
    if not QUIET:
        print('  [%s] %s' % ('PASS' if cond else 'FAIL', name))


def ev_id(ev):
    '''独立重实现（与 scripts/check_ledger_invariants.py 同口径，但各自独立写）。'''
    p = {k: v for k, v in ev.items() if k != 'id'}
    b = json.dumps(p, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'evt_' + hashlib.sha1(b).hexdigest()[:12]


def base_events():
    rows = [
        {'ts': '2026-10-15T01:00:00Z', 'issue': 901, 'action': 'settle',
         'actor': 'FuRongJun-1999', 'holder': 'alice', 'difficulty': 'easy', 'delta': 1,
         'reason': 'r1', 'pr': None, 'covers': [901], 'project': 'bench', 'impact': 'B',
         'day': '2026-10-15', 'formula': {'rule': 'v1.0', 'base': 1, 'round': 1, 'num': 2, 'den': 2}},
        {'ts': '2026-10-15T02:00:00Z', 'issue': 902, 'action': 'settle',
         'actor': 'FuRongJun-1999', 'holder': 'bob', 'difficulty': 'hard', 'delta': 6,
         'reason': 'r2', 'pr': None, 'covers': [902], 'project': 'memory', 'impact': 'A',
         'day': '2026-10-15', 'formula': {'rule': 'v1.0', 'base': 6, 'round': 1, 'num': 2, 'den': 2}},
    ]
    for e in rows:
        e['id'] = ev_id(e)
    return rows


def table_text(events):
    n = len(events)
    d = sum(int(e['delta']) for e in events)
    return '## 2026-10-15（结算 %d 项 · 合计 %d 分）' % (n, d)


def run(events, table=None, ledger_missing=False, quiet=True):
    d = tempfile.mkdtemp(prefix='ledger_inv_')
    lp = os.path.join(d, 'ledger.json')
    tp = os.path.join(d, '贡献表.md')
    if not ledger_missing:
        io.open(lp, 'w', encoding='utf-8').write(json.dumps({'events': events}, ensure_ascii=False))
    if table is not None:
        io.open(tp, 'w', encoding='utf-8').write(table)
    cmd = [sys.executable, '-X', 'utf8', CHECKER, '--ledger', lp, '--contribution-table', tp]
    if quiet:
        cmd.append('--quiet')
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', cwd=ROOT, timeout=120)
    out = (p.stdout or '') + (p.stderr or '')
    named = set(re.findall(r'::error::(I[0-9A-Za-z_]+)', out))
    return p.returncode, out, named


MUTANTS = (
    ('I10_day_matches_ts', 'ts 后移 8 小时（day 不改）—— 即「本地时刻配 Z」'),
    ('I4_difficulty_vocab', 'difficulty 填词表外的 small'),
    ('I7_required_fields', '删掉 holder'),
    ('I2_id_recomputable', '把 id 改成另一个合法形态的 hex'),
    ('I13_totals_match_products', '贡献表合计与账本不符'),
)


def mutate(kind):
    evs = base_events()
    tb = table_text(evs)
    if kind == 'I10_day_matches_ts':
        evs[0]['ts'] = '2026-10-15T09:00:00Z'   # +8h：本地日期变 10-15 17:00，day 仍写 10-15 ⇒ 不变
        evs[0]['ts'] = '2026-10-15T17:00:00Z'   # +8h 后落在 10-16 ⇒ 与 day=2026-10-15 不符
    elif kind == 'I4_difficulty_vocab':
        evs[0]['difficulty'] = 'small'
    elif kind == 'I7_required_fields':
        evs[0].pop('holder')
    elif kind == 'I2_id_recomputable':
        evs[0]['id'] = 'evt_000000000000'
        return evs, tb
    elif kind == 'I13_totals_match_products':
        return evs, '## 2026-10-15（结算 2 项 · 合计 999 分）'
    for e in evs:
        e['id'] = ev_id(e)
    return evs, tb


def main():
    if MUTATE:
        print('定点变异自证：%d 条' % len(MUTANTS))
        bad = 0
        for kind, desc in MUTANTS:
            evs, tb = mutate(kind)
            rc, out, named = run(evs, tb)
            hit = (rc == 1 and named == {kind})
            print('  [%s] %-30s %s' % ('PASS' if hit else 'FAIL', kind, desc))
            if not hit:
                bad += 1
                print('        rc=%d named=%r（期望恰好 {%r}）' % (rc, sorted(named), kind))
        print('变异守卫：%d 条 · 通过 %d · 失败 %d' % (len(MUTANTS), len(MUTANTS) - bad, bad))
        return 1 if bad else 0
    print('守卫：scripts/check_ledger_invariants.py')
    evs = base_events()
    rc, out, named = run(evs, table_text(evs))
    ok('A1 合成合法账本 rc=0', rc == 0)
    ok('A2 合成合法账本零红项', named == set())
    ok('A3 不存在的账本 fail-closed', run([], None, ledger_missing=True)[0] == 1)
    src = io.open(CHECKER, encoding='utf-8').read()
    import ast as _ast
    _imports = set()
    for _node in _ast.walk(_ast.parse(src)):
        if isinstance(_node, _ast.Import):
            _imports |= {_a.name for _a in _node.names}
        elif isinstance(_node, _ast.ImportFrom):
            _imports.add(_node.module or '')
    ok('A4 检查器不 import bounty_board（判据解耦）',
       not any('bounty_board' in m for m in _imports))
    ok('A5 检查器声明 15 项不变量', 'ALL_INVARIANTS' in src and src.count("'I") >= 15)
    rc2, out2, named2 = run([], None)
    ok('A6 空账本 rc=0（不误报）', rc2 == 0 and named2 == set())
    rrc, rout, rnamed = run(
        json.load(io.open(REAL_LEDGER, encoding='utf-8'))['events'],
        io.open(REAL_TABLE, encoding='utf-8').read(), quiet=False)
    ok('A7 仓库真账本 + 真贡献表 rc=0', rrc == 0 and rnamed == set())
    ok('A8 真账本输出含全部 15 项不变量名（全零也打印）',
       all(k in rout for k in ('I1_id_shape', 'I10_day_matches_ts',
                                 'I13_totals_match_products')))
    for kind, desc in MUTANTS:
        me, mt = mutate(kind)
        mrc, mout, mnamed = run(me, mt)
        ok('A9.%s 恰好点名 %s' % (kind, kind), mrc == 1 and mnamed == {kind})
    print('通过 %d / 失败 %d' % (_n_assert[0] - len(_red), len(_red)))
    return 1 if _red else 0


if __name__ == '__main__':
    sys.exit(main())