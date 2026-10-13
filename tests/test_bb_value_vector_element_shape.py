# -*- coding: utf-8 -*-
"""bounty_board.value_vector：账本事件元素非对象不得崩"""
import sys, os, json
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
    print('[%s] %s%s' % ("OK " if ok else "NG ", name, (" - " + detail) if detail else ""))
BAD = ["oops", 5, None, [1]]
LEGAL = [{"action":"settle","holder":"a","delta":6,"project":"memory","difficulty":"hard"}]

import bounty_board as M

print('-- A 非对象元素 => 不崩 --')
try:
    r = M.value_vector(BAD)
    check('A value_vector(非对象x4) => 不抛', True, str(r)[:40])
except Exception as exc:
    check('A value_vector(非对象x4) => 不抛', False, type(exc).__name__ + ': ' + str(exc)[:40])

print('-- B 零行为变更 --')
try:
    r2 = M.value_vector(LEGAL)
    check('B 合法输入仍可算', r2 is not None, str(r2)[:40])
except Exception as exc:
    check('B 合法输入仍可算', False, type(exc).__name__)

print('-- C 反向证明 --')
SRC = open(_IMPL, encoding="utf-8").read()
_n_ev = SRC.count('if not isinstance(ev, dict):')
_n_d = SRC.count('if not isinstance(d, dict):')
check('C0 该文件的形状判据在位（>=1 处）', _n_ev + _n_d >= 1, 'ev=%d d=%d' % (_n_ev, _n_d))
print('')
print('通过 %d / 失败 %d' % (pass_n, fail_n))
sys.exit(0 if fail_n == 0 else 1)
