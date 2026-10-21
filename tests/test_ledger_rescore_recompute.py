# -*- coding: utf-8 -*-
"""test_ledger_rescore_recompute.py · **已落盘账本必须可被独立复算**的守卫

背景（2026-10-13 修复）：`docs/bounty/ledger.json` 的 13 条早期事件的 `formula` 快照
只写了 `{"kind": "complete", "round": 1}`，**缺 `rule` 字段**。`rescore()` 按
`formula.rule` 分派，缺该字段即报 `unknown rule None` ⇒ 这 13 条无法被独立复算。

而 `docs/bounty/README.md` 对第三方承诺「可复算入口」。**承诺在文档里、判据在代码里、
证据在数据里**——三者此前没有任何一处把它们绑起来：全仓没有任何测试或 CI 步骤
拿**真实已落盘账本**跑过 `rescore`（`scripts/check_plan.py` 零引用）。

本守卫补上这一环，四组：
 A 数据面：真实账本每条事件都有 `formula.rule == SCORE_RULE`（缺即红）；
 B 复算面：`rescore(真实账本 events)` 必须 `ok=True`、`bad` 为空；
 C 口径面：`_schema` 里宣称的计分口径与 `DIFFICULTY_SCORES` 一致（与 #168 守卫互补）；
 D 反向证明：把账本里任一事件的 `formula` 挖掉 `rule` ⇒ 同一套 B 必须**变红**
   （证明 B 有判别力，不是恒真）。

体例与 `tests/` 下其它 test_*.py 一致（`check()` + 退出码；末行「通过 N / 失败 M」）。
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, 'scripts'))
import bounty_board as bb

LEDGER = os.path.join(_REPO, 'docs', 'bounty', 'ledger.json')
pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'BAD', name, ' — ' + detail if detail else ''))


print('— A 数据面（真实账本每条 formula 都带 rule）—')
check('A0 账本存在', os.path.isfile(LEDGER), LEDGER)
DOC = json.loads(io.open(LEDGER, encoding='utf-8').read())
EV = DOC.get('events') or []
check('A1 账本有事件', len(EV) > 0, '%d 条' % len(EV))
#: 认**全部合法 rule**（含维护者直接裁决档），不是只认 SCORE_RULE——
#: 账本里 #293（2026-10-15，delta=40）用的是 `maintainer_direct_ruling`，
#: 那是维护者对单个 issue 的直接定分，**不是坏数据**。旧断言只认 SCORE_RULE
#: ⇒ 把合法裁决判成缺项，本守卫自 2026-10-15 起一直红。
_missing = [e.get('id') for e in EV
            if (e.get('formula') or {}).get('rule') not in bb.KNOWN_RULES]
check('A2 每条事件的 formula.rule 属于 KNOWN_RULES', not _missing,
      ('缺/不符 %d 条：%s' % (len(_missing), _missing[:4])) if _missing else '共 %d 条' % len(EV))
check('A3 每条事件都有 id', all(e.get('id') for e in EV))

print('— B 复算面（rescore 对真实账本必须 ok）—')
ok, bad = bb.rescore(EV)
check('B1 rescore(真实账本) ok=True', ok, 'bad=%d' % len(bad))
check('B2 bad 为空', not bad, str(bad[:3]) if bad else '')

print('— C 口径面（_schema 宣称的难度表与权威单点一致）—')
SC = (DOC.get('_schema') or {}).get('计分') or {}
EXPECT = {k.split(':', 1)[-1]: v for k, v in bb.DIFFICULTY_SCORES.items()}
_got = {k: v for k, v in SC.items() if k in EXPECT}
check('C1 _schema.计分 的难度表 == DIFFICULTY_SCORES 派生值', _got == EXPECT,
      'schema=%s expect=%s' % (_got, EXPECT))

print('— D 反向证明（挖掉 rule ⇒ B 必须变红）—')
MUT = [dict(e) for e in EV]
_first = next((i for i, e in enumerate(MUT) if (e.get('formula') or {}).get('rule')), None)
check('D0 变异锚点存在', _first is not None)
if _first is not None:
    _f = dict(MUT[_first]['formula'])
    _f.pop('rule', None)
    MUT[_first] = dict(MUT[_first])
    MUT[_first]['formula'] = _f
    ok2, bad2 = bb.rescore(MUT)
    check('D 挖掉一条 rule ⇒ rescore ok=False 且 bad 命中该条',
          (not ok2) and any(b[0] == MUT[_first].get('id') for b in bad2),
          'bad=%d' % len(bad2))

print()
print('通过 %d / 失败 %d' % (pass_n, fail_n))
sys.exit(1 if fail_n else 0)