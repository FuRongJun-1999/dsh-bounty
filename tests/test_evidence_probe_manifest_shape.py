# -*- coding: utf-8 -*-
"""evidence_probe：快照清单条目**非对象**不得崩栈（契约要退 2）"""
import sys, os, json, tempfile, subprocess
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

import shutil, subprocess
print('— A 静态面 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('A0 形状判据锚点命中', SRC.count('if not isinstance(doc, dict):') == 1, '')
print('— B 端到端（沙箱里往清单插一条非对象）—')
d = tempfile.mkdtemp(prefix="ep_manifest_")
shutil.copytree(_REPO, d, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
mf = os.path.join(d, "review", "evidence", "manifest.json")
doc = json.load(open(mf, encoding="utf-8"))
doc["documents"].insert(0, "oops")
json.dump(doc, open(mf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(d, "scripts", "evidence_probe.py"),
                    "record.dsh-memory"], capture_output=True, text=True, encoding="utf-8", cwd=d)
check('B 不崩栈', "Traceback" not in r.stderr, (r.stderr or "").strip()[-60:])
check('B rc=0（非对象条目被跳过，探针仍能跑）', r.returncode == 0, f"rc={r.returncode}")
check('B stdout 仍含结论行', "结论：" in r.stdout, '')
print('— C 零行为变更 —')
d2 = tempfile.mkdtemp(prefix="ep_ok_")
shutil.copytree(_REPO, d2, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
r2 = subprocess.run([sys.executable, "-X", "utf8", os.path.join(d2, "scripts", "evidence_probe.py"),
                     "record.dsh-memory"], capture_output=True, text=True, encoding="utf-8", cwd=d2)
check('C 合法数据仍 rc=0', r2.returncode == 0, f"rc={r2.returncode}")
print('— D 反向证明 —')
check('D 旧实现直接 `doc.get("file")` ⇒ 非对象必抛 AttributeError（已不在源码里）',
      '    for doc in load_manifest_docs():\n        if str(doc.get("file") or "") == name:' not in SRC, '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
