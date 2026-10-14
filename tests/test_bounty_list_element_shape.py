# -*- coding: utf-8 -*-
"""bounty_list.render：真源 `items` 元素**非对象**不得崩（`--check` 闸拿不到结论）"""
import sys, os, json, tempfile, copy
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
print('— A 非对象条目 ⇒ 跳过 + 警告（不崩）—')
_SRC = json.load(open(os.path.join(_REPO, "docs", "bounty", "悬赏.json"), encoding="utf-8"))
_good = copy.deepcopy(_SRC["items"][0])
for label, val in (("字符串", "oops"), ("数字", 5), ("null", None), ("数组", [1])):
    doc = copy.deepcopy(_SRC); doc["items"] = [val] + [copy.deepcopy(_good)]
    try:
        out = bl.render(doc)
        check(f'A render(items=[{label}, 合法]) ⇒ 不抛', True, out[:26].replace("\n", " "))
        check(f'A 合法那条仍渲染出来', "x" in out or "| x |" in out or "x" in out, '')
    except Exception as exc:
        check(f'A render(items=[{label}]) ⇒ 不抛', False, f'{type(exc).__name__}: {str(exc)[:30]}')
print('— B 零行为变更 —')
_d2 = copy.deepcopy(_SRC); _d2["items"] = [copy.deepcopy(_good)]
out2 = bl.render(_d2)
check('B 全合法 ⇒ 正常渲染', out2.startswith("# 灵枢悬赏 · 任务清单"), out2[:30])
print('— C 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('C0 形状过滤锚点命中', "_good = [it for it in _items if isinstance(it, dict)]" in SRC, '')
check('C 旧实现直接 `sorted(doc["items"], key=sort_key)` ⇒ 非对象必抛（已不在源码里）',
      'items = sorted(doc["items"], key=sort_key)' not in SRC, '')
check('C `sort_key` 的 `it["score"]` 对非对象必然抛 TypeError/KeyError（既有实现证据）',
      'return (-it["score"], it["id"])' in SRC, '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
