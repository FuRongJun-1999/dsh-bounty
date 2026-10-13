# -*- coding: utf-8 -*-
"""evidence_check.audit：evidence 元素**非对象**不得崩栈（同仓另两件都点名）"""
import sys, os, json, tempfile, importlib.util, shutil, subprocess
sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "evidence_check.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"\u2713" if ok else "\u2718"}] {name}{(" \u2014 " + detail) if detail else ""}')

import evidence_check as ec
print('— A 静态面：两处循环都有 isinstance 判据 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('A0 出处循环的形状判据在位', "证据条目不是对象：%s 的 evidence[%d] 实为 %s" in SRC, '')
check('A 复算循环也有判据', SRC.count("                    if not isinstance(e, dict):") == 1, '')
print('— B 端到端：把 evidence 元素换成非对象 —')
def _mk(ev0):
    d = tempfile.mkdtemp(prefix="ec_elem_")
    shutil.copytree(_REPO, d, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    pj = os.path.join(d, "review", "data", "plugins.json")
    doc = json.load(open(pj, encoding="utf-8"))
    doc["records"][0]["evidence"][0] = ev0
    json.dump(doc, open(pj, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    r = subprocess.run([sys.executable, "-X", "utf8",
                        os.path.join(d, "scripts", "evidence_check.py"), "--root", d, "--no-repro", "--quiet"],
                       capture_output=True, text=True, encoding="utf-8", cwd=d)
    return d, r
for label, val in (("字符串", "我被换成字符串了"), ("数字", 5), ("数组", [1]), ("null", None)):
    _d, r = _mk(val)
    check(f'B evidence[0]={label} ⇒ 不崩栈', "Traceback" not in r.stderr, (r.stderr or "").strip()[-60:])
    check(f'B evidence[0]={label} ⇒ rc=1（检出问题）', r.returncode == 1, f"rc={r.returncode}")
print('— C 合法数据零行为变更 —')
d0 = tempfile.mkdtemp(prefix="ec_ok2_")
shutil.copytree(_REPO, d0, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(d0, "scripts", "evidence_check.py"),
                    "--root", d0], capture_output=True, text=True, encoding="utf-8", cwd=d0)
check('C 合法数据仍 rc=0', r.returncode == 0, f"rc={r.returncode}")
print('— D 反向证明 —')
check('D 旧实现直接 `e.get(...)` ⇒ 非对象必抛 AttributeError',
      "if not isinstance(e, dict):\n                bad.append(\"证据条目不是对象" in SRC, '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
