# -*- coding: utf-8 -*-
"""bounty_list.validate：items 元素**非对象**须 fail-closed 点名（不再裸 AttributeError）"""
import sys, os, json, tempfile, subprocess
sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "bounty_list.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print('[%s] %s%s' % ("OK " if ok else "NG ", name, (" — " + detail) if detail else ""))

import bounty_list as bl
print('— A 非对象条目 ⇒ 不崩、且被点名 —')
for label, val in (("字符串", "oops"), ("数字", 5), ("null", None), ("数组", [1])):
    try:
        errs = bl.validate({"items": [val]})
        check(f'A items=[{label}] ⇒ 不抛', True, str(errs[:1])[:56])
        check(f'A items=[{label}] ⇒ 点名「非对象条目」', any("非对象条目" in e for e in errs), str(errs)[:60])
    except Exception as exc:
        check(f'A items=[{label}] ⇒ 不抛', False, f'{type(exc).__name__}: {exc}')
print('— B 零行为变更 —')
e = bl.validate({"items": [{"id": "x", "title": "t", "direction": "d", "difficulty": "easy",
                           "score": 1, "form": "f", "status": "open",
                           "acceptance": ["a"], "refs": ["r"], "boundary": ["b"]}]})
check('B 合法条目无「非对象」错误', not any("非对象条目" in x for x in e), str(e)[:60])
check('B 空 items 仍报缺失', any("缺失或为空" in x for x in bl.validate({"items": []})), '')
print('— C 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('C0 形状判据锚点命中', SRC.count('if not isinstance(it, dict):') == 1, '')
check('C 旧实现直接 `it.get("id", "?")` ⇒ 非对象必抛 AttributeError（已不在源码里）',
      'for it in doc.get("items", []):\n        i = it.get("id", "?")' not in SRC, '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
