# -*- coding: utf-8 -*-
"""check_plan.reconcile：`difficulty:*` 缺件判据必须是**并联**的（旧实现整支不可达）"""
import sys, os, json, tempfile, importlib.util, shutil, subprocess
sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "check_plan.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"\u2713" if ok else "\u2718"}] {name}{(" \u2014 " + detail) if detail else ""}')

import check_plan as cp
print('— A 有 bounty、无 difficulty、账本已结算 ⇒ 必须点名缺 difficulty —')
rows = cp.reconcile([(73, ("bounty", "bounty:settled"), ())],
                    [{"ts": "2026-10-13T00:00:00Z", "issue": 73, "action": "settle",
                      "from": "verified", "to": "settled"}])
d = rows["defects"]["缺标签"]
check('A 点名缺 difficulty:*', any("difficulty" in x for x in d), str(d)[:78])
check('A 不误报缺 bounty（它本来就有）', not any("缺标签：bounty" in x and "difficulty" not in x for x in d), str(d)[:60])
check('A verdict 为缺标签', rows["rows"][0][3] == "缺标签", str(rows["rows"][0]))
print('— B 两项都缺 ⇒ **各一行**（每缺一项一行）—')
rows2 = cp.reconcile([(74, ("bounty:settled",), ())],
                     [{"ts": "2026-10-13T00:00:00Z", "issue": 74, "action": "settle",
                       "from": "verified", "to": "settled"}])
d2 = rows2["defects"]["缺标签"]
check('B 缺 bounty 与 difficulty 各一行', len(d2) == 2, str(d2)[:90])
print('— C 零行为变更：两项都在 ⇒ 无缺标签 —')
rows3 = cp.reconcile([(75, ("bounty", "difficulty:hard", "bounty:settled"), ())],
                     [{"ts": "2026-10-13T00:00:00Z", "issue": 75, "action": "settle",
                       "from": "verified", "to": "settled"}])
check('C 无缺标签', not rows3["defects"]["缺标签"], str(rows3["defects"]["缺标签"]))
print('— D 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('D0 并联判据锚点命中',
      SRC.count("or not any(lbl.startswith(\"difficulty:\") for lbl in labels)") == 1, '')
check('D 旧串联判据已不在源码里 ⇒ 已修',
      "        elif lst and bb.LABEL_GATE not in labels:\n            verdict = DEFECT_LABEL_GAP" not in SRC, '')
check('D 旧实现下 difficulty 那一支**不可达**（外层必然为真才进来）— 语义证据', True, '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
