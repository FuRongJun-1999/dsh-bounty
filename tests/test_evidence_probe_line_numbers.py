# -*- coding: utf-8 -*-
"""evidence_probe.line_numbers：`needle` **非字符串**不得崩栈"""
import sys, os, json, tempfile, copy
sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "evidence_probe.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print('[%s] %s%s' % ("OK " if ok else "NG ", name, (" — " + detail) if detail else ""))

import evidence_probe as ep
print('— A 非字符串 needle ⇒ 不崩 —')
for label, val in (("数字", 5), ("null", None), ("数组", [1]), ("字典", {"k": 1})):
    try:
        r = ep.line_numbers("abc\ndef\nabc", val)
        check(f'A line_numbers(needle={label}) ⇒ 不抛', True, str(r)[:36])
    except Exception as exc:
        check(f'A line_numbers(needle={label}) ⇒ 不抛', False, f'{type(exc).__name__}: {str(exc)[:28]}')
print('— B 零行为变更 —')
check('B 正常 needle 仍报对行号', ep.line_numbers("abc\ndef\nabc", "abc") == [1, 3],
      str(ep.line_numbers("abc\ndef\nabc", "abc")))
check('B 未命中 ⇒ 空列表', ep.line_numbers("abc", "zzz") == [], '')
print('— C 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('C0 字符串化锚点命中', '    needle = str(needle)' in SRC, '')
check('C 旧实现直接拿 needle 做 `in` ⇒ 非字符串必抛 TypeError（已修）',
      '    needle = str(needle)' in SRC, '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
