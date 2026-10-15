#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账本结构不变量自审：把 round-46 手工跑出来的清单固化为可重复执行的判据。

  python -X utf8 scripts/check_ledger_invariants.py [--ledger PATH] [--contribution-table PATH] [--quiet]

为什么需要（2026-10-15 立）：
  本站连续多轮把「查删除行／跑漂移闸／机械复算」用在其它仓上，却从未把这些手段用回自己的账本。
  round-46 首次手工自审，立刻查出 11 行的 ts 是「本地时刻配 Z 后缀」（差 8 小时，day 与
  date(ts+8h) 不符）——同一批里 9 行的 ts 完全相同，是 round-30 一次性重写留下的指纹。
  手工自审的问题与其它「有人写了没人跑」的守卫一样：下一次不一定有人想起来跑。

设计约束（照 tests/ 的既有约定）：
  · 不 import bounty_board —— id 公式在本文件独立重实现。否则「同错同绿」：公式若被改坏，
    检查器会跟着一起变，永远发现不了。守卫要当独立见证者。
  · fail-closed：任何一项非零即 rc=1 并逐条点名（条目名可 grep）；全零才 rc=0。
  · 不触网、零第三方依赖。
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF_LEDGER = os.path.join(ROOT, 'docs', 'bounty', 'ledger.json')
DEF_TABLE = os.path.join(ROOT, 'docs', 'bounty', '贡献表.md')

DIFFICULTY_BASE = {'easy': 1, 'medium': 3, 'hard': 6, 'expert': 10}
IMPACT_GRADES = ('S', 'A', 'B', 'C', 'D')
TS_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
ID_RE = re.compile(r'^evt_[0-9a-f]{12}$')
SUM_RE = re.compile(r'（结算 (\d+) 项 · 合计 (\d+) 分）')

ALL_INVARIANTS = ('I1_id_shape', 'I2_id_recomputable', 'I3_id_unique',
                  'I4_difficulty_vocab', 'I5_delta_type', 'I6_impact_vocab',
                  'I7_required_fields', 'I7b_action_is_settle', 'I8_covers_missing',
                  'I8b_covers_shape', 'I9_ts_shape', 'I10_day_matches_ts',
                  'I11_formula_self_consistent', 'I12_project_present',
                  'I13_totals_match_products')


def event_id(ev):
    payload = {k: v for k, v in ev.items() if k != 'id'}
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
    return 'evt_' + hashlib.sha1(blob).hexdigest()[:12]


def _day_of(ts):
    t = datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
    return (t + datetime.timedelta(hours=8)).strftime('%Y-%m-%d')


def audit(events, table_text=None):
    d = collections.defaultdict(list)
    ids = collections.Counter()
    ts_prev = ''
    inversions = []
    total = 0
    for i, e in enumerate(events):
        n = i + 1
        eid = e.get('id')
        if not isinstance(eid, str) or not ID_RE.match(eid):
            d['I1_id_shape'].append((n, eid))
        else:
            ids[eid] += 1
            if event_id(e) != eid:
                d['I2_id_recomputable'].append((n, e.get('issue'), eid, event_id(e)))
        dv = e.get('difficulty')
        if dv not in DIFFICULTY_BASE:
            d['I4_difficulty_vocab'].append((n, e.get('issue'), dv))
        delta = e.get('delta')
        if not isinstance(delta, int) or isinstance(delta, bool):
            d['I5_delta_type'].append((n, e.get('issue'), repr(delta)))
        else:
            total += delta
        if e.get('impact') not in IMPACT_GRADES:
            d['I6_impact_vocab'].append((n, e.get('issue'), e.get('impact')))
        for f in ('action', 'actor', 'holder'):
            if not e.get(f):
                d['I7_required_fields'].append((n, e.get('issue'), f))
        if e.get('action') != 'settle':
            d['I7b_action_is_settle'].append((n, e.get('issue'), e.get('action')))
        c = e.get('covers')
        if c is None:
            d['I8_covers_missing'].append((n, e.get('issue')))
        elif not isinstance(c, list) or any(
                not isinstance(x, int) or isinstance(x, bool) for x in c):
            d['I8b_covers_shape'].append((n, e.get('issue'), repr(c)[:60]))
        ts = e.get('ts') or ''
        if not TS_RE.match(ts):
            d['I9_ts_shape'].append((n, e.get('issue'), ts))
        else:
            if e.get('day') != _day_of(ts):
                d['I10_day_matches_ts'].append((n, e.get('issue'), ts, e.get('day'), _day_of(ts)))
            if ts_prev and ts < ts_prev:
                inversions.append((n, ts, ts_prev))
            ts_prev = ts
        if not isinstance(e.get('project'), str) or not e.get('project'):
            d['I12_project_present'].append((n, e.get('issue'), e.get('project')))
        f = e.get('formula')
        if isinstance(f, dict) and f.get('round') == 1 and f.get('num') == f.get('den'):
            if e.get('delta') != f.get('base'):
                d['I11_formula_self_consistent'].append((n, e.get('issue'), e.get('delta'), f.get('base')))
    dup = sorted(k for k, v in ids.items() if v > 1)
    if dup:
        d['I3_id_unique'].append(('dups', dup))
    stat = {'rows': len(events), 'delta': total, 'inversions': len(inversions)}
    if inversions:
        stat['inversion_detail'] = inversions[:5]
    if table_text is not None:
        m = SUM_RE.findall(table_text)
        ti = sum(int(a) for a, b in m)
        tp = sum(int(b) for a, b in m)
        stat['table'] = {'items': ti, 'points': tp}
        if (ti, tp) != (len(events), total):
            d['I13_totals_match_products'].append(('table', ti, tp, len(events), total))
    return d, stat


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--ledger', default=DEF_LEDGER)
    ap.add_argument('--contribution-table', default=DEF_TABLE)
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args(argv)
    if not os.path.isfile(args.ledger):
        print('::error::账本不存在：%s' % args.ledger)
        return 1
    obj = json.load(io.open(args.ledger, encoding='utf-8'))
    events = obj['events'] if isinstance(obj, dict) and 'events' in obj else obj
    table = None
    if os.path.isfile(args.contribution_table):
        table = io.open(args.contribution_table, encoding='utf-8').read()
    else:
        print('[SKIP] I13_totals_match_products —— 未找到贡献表 %s' % args.contribution_table)
    bad, stat = audit(events, table)
    print('账本不变量自审：%d 项 · 非零 %d 项 · 行 %d · Δ%d'
          % (len(ALL_INVARIANTS), len(bad), stat['rows'], stat['delta']))
    if not args.quiet:
        for k in ALL_INVARIANTS:
            print('  [%2d] %s' % (len(bad.get(k) or []), k))
    for k in ALL_INVARIANTS:
        v = bad.get(k)
        if not v:
            continue
        print('::error::%s —— %d 处' % (k, len(v)))
        for x in v[:8]:
            print('    %r' % (x,))
        if len(v) > 8:
            print('    …（其余 %d 处省略）' % (len(v) - 8))
    if stat['inversions']:
        print('[NOTE] ts 非单调 %d 处（不判红：后来追加的行可携带更早的 ts）%r'
              % (stat['inversions'], stat.get('inversion_detail')))
    print('判据解耦声明：本文件不 import bounty_board，id 公式独立重实现，以当独立见证者。')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())