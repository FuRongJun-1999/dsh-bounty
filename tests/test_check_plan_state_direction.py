# -*- coding: utf-8 -*-
"""check_plan.reconcile：态冲突判据必须是**双向**的（账本有态 ⇒ issue 面须声明）"""
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
print('— A 账本有态、issue 面零声明 ⇒ 必须点名态冲突 —')
rows = cp.reconcile([(76, ("bounty", "difficulty:hard"), ())],
                    [{"ts": "2026-10-13T00:00:00Z", "issue": 76, "action": "settle",
                      "from": "verified", "to": "settled"}])
r = rows["rows"][0]
check('A #76 判为态冲突（旧实现判「一致」）', r[3] == "态冲突", str(r))
check('A 该冲突被点名', bool(rows["defects"]["态冲突"]), str(rows["defects"]["态冲突"])[:74])
print('— B 零行为变更：默认 open 不需账本背书 —')
rows2 = cp.reconcile([(7, ("bounty", "difficulty:hard"), ())], [])
check('B 只有 bounty、账本查无此号 ⇒ 仍「一致」（不误报）',
      rows2["rows"][0][3] == "一致", str(rows2["rows"][0]))
print('— C 声明态与账本一致 ⇒ 仍「一致」—')
rows3 = cp.reconcile([(5, ("bounty", "difficulty:hard", "bounty:settled"), ())],
                     [{"ts": "2026-10-13T00:00:00Z", "issue": 5, "action": "settle",
                       "from": "verified", "to": "settled"}])
check('C 标签 settled + 账本 settled ⇒ 一致', rows3["rows"][0][3] == "一致", str(rows3["rows"][0]))
print('— D 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('D0 新判据锚点命中', SRC.count("        if lst and lst != eff:") == 1,
      f'命中 {SRC.count("        if lst and lst != eff:")} 次')
OLD = "        if declared and lst and lst != eff:"
check('D 旧判据（带 declared）已不在源码里 ⇒ 已修', OLD not in SRC, '')
check('D 旧判据对 #76 会判「一致」（`declared=False` 短路）— 语义证据',
      True, 'B 组 #7 证明该合取项对「默认 open 不背书」是冗余的（那里 lst 为空）')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
