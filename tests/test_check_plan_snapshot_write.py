# -*- coding: utf-8 -*-
"""check_plan_snapshot：`write_snapshot` 的 `OSError` 须按契约退 1（不再裸栈）"""
import sys, os, json, tempfile, importlib.util, shutil, subprocess
sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "check_plan_snapshot.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"\u2713" if ok else "\u2718"}] {name}{(" \u2014 " + detail) if detail else ""}')

import check_plan_snapshot as cs
print('— A 静态面：写盘调用在 try 内 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('A0 `try:` + `except OSError` 包住 write_snapshot',
      "    try:\n        path = write_snapshot(doc, args.out)\n    except OSError as exc:" in SRC, '')
check('A 错误串含「快照写不出去」', "快照写不出去" in SRC, '')
print('— B 端到端：输出路径不可写（盘符非法 / 目录不存在）—')
_orig_build = cs.build_snapshot
cs.build_snapshot = lambda repo=cs.DEFAULT_REPO: {"_schema": "x", "items": []}
try:
    bad = "Z:\\nope\\out.json" if os.name == "nt" else "/proc/nope/out.json"
    rc = cs.main(["--out", bad])
    check('B 写盘失败 ⇒ 退 1（契约值）', rc == 1, f"rc={rc}")
    # 目录不存在的情形（父目录会自动创建，故用盘符非法那条覆盖）
finally:
    cs.build_snapshot = _orig_build
print('— C 零行为变更：正常路径仍退 0 并写出文件 —')
d = tempfile.mkdtemp(prefix="cs_ok_")
cs.build_snapshot = lambda repo=cs.DEFAULT_REPO: {"_schema": "x", "items": []}
try:
    out = os.path.join(d, "sub", "out.json")
    rc = cs.main(["--out", out])
    check('C 正常路径 rc=0 且写盘', rc == 0 and os.path.isfile(out), f"rc={rc} exists={os.path.isfile(out)}")
finally:
    cs.build_snapshot = _orig_build
print('— D 反向证明 —')
check('D 旧实现把 `path = write_snapshot(...)` 放在 try 之外（无 except OSError）⇒ 抛裸栈',
      "except OSError as exc:\n        print(f\"[error] 快照写不出去" in SRC, '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
