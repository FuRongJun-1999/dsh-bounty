# -*- coding: utf-8 -*-
"""review_build.render_detail：evidence 元素**非对象**不得崩栈"""
import sys, os, json, tempfile, subprocess
sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "review_build.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print('[%s] %s%s' % ("OK " if ok else "NG ", name, (" — " + detail) if detail else ""))

import review_build as rb
import copy
_PJ = os.path.join(_REPO, "review", "data", "plugins.json")
_DOC = json.load(open(_PJ, encoding="utf-8"))
def _rec(ev):
    """取一条**真实记录**、只替换 evidence —— 避免猜字段。"""
    d = copy.deepcopy(_DOC["records"][0])
    d["evidence"] = [ev]
    return d
print('— A render_detail 元素非对象 —')
for label, val in (("字符串", "oops"), ("数字", 5), ("null", None), ("数组", [1])):
    try:
        h = rb.render_detail(_rec(val))
        check(f'A evidence=[{label}] ⇒ 不抛', True, h[:34].replace("\n", " "))
        check(f'A 渲染出「非对象条目」提示', "非对象条目" in h, '')
    except Exception as exc:
        check(f'A evidence=[{label}] ⇒ 不抛', False, f'{type(exc).__name__}: {str(exc)[:34]}')
print('— B 零行为变更 —')
try:
    h2 = rb.render_detail(copy.deepcopy(_DOC["records"][0]))   # 原样记录 = 合法样本
    check('B 合法证据仍正常渲染', "证据 1" in h2 and "非对象条目" not in h2, h2[:30])
except Exception as exc:
    check('B 合法证据仍正常渲染', False, f'{type(exc).__name__}')
print('— C 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('C0 形状判据锚点命中', 'if not isinstance(e, dict):' in SRC, '')
check('C 旧实现直接 `e.get("kind")` ⇒ 非对象必抛（已不在源码里）',
      '    for i, e in enumerate(d["evidence"], 1):\n        kind = str(e.get("kind")' not in SRC, '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
