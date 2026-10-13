# -*- coding: utf-8 -*-
"""daily_table：账本事件**元素非对象**不得崩栈（贡献表由账本机械生成）"""
import sys, os, json, tempfile, subprocess
sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "daily_table.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print('[%s] %s%s' % ("OK " if ok else "NG ", name, (" — " + detail) if detail else ""))

import daily_table as dt
print('— A 非对象事件 ⇒ 不崩 —')
for label, val in (("字符串", "oops"), ("数字", 5), ("null", None), ("数组", [1])):
    try:
        r = dt.group_by_day([val, {"action": "settle", "day": "2026-10-13", "delta": 3}])
        check(f'A group_by_day([{label}, 合法]) ⇒ 不抛', True, str(list(r))[:36])
        check(f'A 合法那条仍入组', "2026-10-13" in r, str(list(r))[:36])
    except Exception as exc:
        check(f'A group_by_day([{label}]) ⇒ 不抛', False, f'{type(exc).__name__}')
try:
    t = dt.render(["oops", 5])
    check('A render([非对象]) ⇒ 不抛', True, t.splitlines()[0][:40])
except Exception as exc:
    check('A render([非对象]) ⇒ 不抛', False, f'{type(exc).__name__}')
print('— B 零行为变更 —')
check('B 合法账本仍分组正确',
      dt.group_by_day([{"action": "settle", "day": "2026-10-13", "delta": 3}]).get("2026-10-13") is not None, '')
print('— C 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('C0 形状判据锚点命中', SRC.count('if not isinstance(ev, dict):') == 1, '')
check('C 旧实现直接 `ev.get("action")` ⇒ 非对象必抛（已不在源码里）',
      '    for ev in events or []:\n        if ev.get("action") != "settle":' not in SRC, '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
