# -*- coding: utf-8 -*-
"""build_site：账本事件与 tasks 快照的**元素非对象**不得崩栈"""
import sys, os, json, tempfile, subprocess
sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "build_site.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print('[%s] %s%s' % ("OK " if ok else "NG ", name, (" — " + detail) if detail else ""))

import build_site as bs
print('— A latest_by_issue 元素非对象 —')
for label, val in (("字符串", "oops"), ("数字", 5), ("null", None)):
    try:
        r = bs.latest_by_issue([val, {"issue": 1, "to": "open"}])
        check(f'A latest_by_issue([{label}, 合法]) ⇒ 不抛', True, str(r)[:40])
        check(f'A 合法那条仍被收录', r.get("1", {}).get("to") == "open", str(r)[:40])
    except Exception as exc:
        check(f'A latest_by_issue([{label}]) ⇒ 不抛', False, f'{type(exc).__name__}')
print('— B open_tasks(tasks) 元素非对象 —')
try:
    out = bs.open_tasks([], ["oops", 5, None])
    check('B open_tasks(tasks=[非对象]) ⇒ 不抛', True, str(out)[:40])
except Exception as exc:
    check('B open_tasks(tasks=[非对象]) ⇒ 不抛', False, f'{type(exc).__name__}')
print('— C 零行为变更 —')
r2 = bs.latest_by_issue([{"issue": 7, "to": "open", "difficulty": "hard"}])
check('C 合法账本仍正确', r2.get("7", {}).get("to") == "open", str(r2)[:50])
print('— D 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('D0 两处形状判据锚点命中', SRC.count('if not isinstance(ev, dict):') == 1
      and SRC.count('if not isinstance(t, dict):') == 1,
      'ev=%d t=%d' % (SRC.count('if not isinstance(ev, dict):'), SRC.count('if not isinstance(t, dict):')))
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
