# -*- coding: utf-8 -*-
"""bounty_board：账本事件／评论元素**非对象、非字符串**不得崩栈"""
import sys, os, json, tempfile, copy
sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "bounty_board.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print('[%s] %s%s' % ("OK " if ok else "NG ", name, (" — " + detail) if detail else ""))

import bounty_board as bb
print('— A rescore：非对象元素 ⇒ 结构化 bad（不崩）—')
for label, val in (("字符串", "oops"), ("数字", 5), ("null", None), ("数组", [1])):
    try:
        ok, bad = bb.rescore([val, {"id": "e1", "delta": 0, "formula": None}])
        check(f'A rescore([{label}]) ⇒ 不抛', True, f'ok={ok} bad={len(bad)}')
        check(f'A rescore([{label}]) ⇒ 点名 malformed event',
              any("malformed event" in str(b[1]) for b in bad), str(bad[:1])[:56])
    except Exception as exc:
        check(f'A rescore([{label}]) ⇒ 不抛', False, f'{type(exc).__name__}')
print('— B role_revocations：非对象元素 ⇒ 跳过 —')
for label, val in (("字符串", "oops"), ("数字", 5), ("null", None), ("数组", [1])):
    try:
        r = bb.role_revocations([val, {"action": "role", "subject": "a", "role": "reviewer", "op": "grant"}])
        check(f'B role_revocations([{label}]) ⇒ 不抛', True, str(r)[:40])
    except Exception as exc:
        check(f'B role_revocations([{label}]) ⇒ 不抛', False, f'{type(exc).__name__}')
print('— C latest_marker：非字符串评论 ⇒ 跳过（docstring 承诺「坏 JSON 一律跳过，不抛」）—')
for label, val in (("数字", 5), ("null", None), ("数组", [1])):
    try:
        bb.latest_marker([val, "<!-- bounty:v1 {} -->"])
        check(f'C latest_marker([{label}]) ⇒ 不抛', True, '')
    except Exception as exc:
        check(f'C latest_marker([{label}]) ⇒ 不抛', False, f'{type(exc).__name__}')
print('— D 零行为变更 —')
ok2, bad2 = bb.rescore([{"id": "e1", "delta": 0, "formula": None}])
check('D 合法事件仍正常', ok2 is True and bad2 == [], f'{ok2} {bad2}')
_rev = bb.role_revocations([{"action": "role", "subject": "a", "role": "reviewer", "op": "revoke"}])
check('D role_revocations 合法 revoke 事件仍进集合', "a" in (_rev.get("reviewer") or set()), str(_rev)[:48])
_gr = bb.role_revocations([{"action": "role", "subject": "b", "role": "reviewer", "op": "grant"}])
check('D grant 不进撤销集合（语义未变）', "b" not in (_gr.get("reviewer") or set()), str(_gr)[:48])
print('— E 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('E0 三处形状判据锚点命中',
      SRC.count("if not isinstance(ev, dict):") >= 2 and SRC.count("if not isinstance(body, str):") == 1,
      'ev=%d body=%d' % (SRC.count("if not isinstance(ev, dict):"), SRC.count("if not isinstance(body, str):")))
check('E 旧实现直接 `ev.get("formula")` ⇒ 非对象必抛（已不在源码里）',
      '    for ev in events or []:\n        f = ev.get("formula")' not in SRC, '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
