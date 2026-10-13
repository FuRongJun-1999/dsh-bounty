# -*- coding: utf-8 -*-
"""evidence_check：`--root` 必须也管到**复算段**（同一个 root 不得给出两种判决）"""
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
PY = sys.executable
print('— A 静态面：探针路径由 base 派生 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('A0 签名含 base 形参', "def load_probe_module(base=None):" in SRC, '')
check('A 路径由 base 派生',
      'script = os.path.join(base, "scripts", "evidence_probe.py") if base else PROBE_SCRIPT' in SRC, '')
check('A 调用点传 base', "load_probe_module(base)" in SRC, '')
check('A 错误串也用 script（不再硬编码 PROBE_SCRIPT）',
      '"找不到探针脚本：%s" % script' in SRC and '"探针模块缺 render()：%s" % script' in SRC, '')
print('— B 端到端：交付仓脚本 + --root 沙箱 ⇒ 判定须与沙箱自带脚本一致 —')
sb = tempfile.mkdtemp(prefix="ec_root_")
shutil.copytree(_REPO, sb, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
# 沙箱里改一份快照 + 同步清单，使沙箱自身账实相符
snap = os.path.join(sb, "review", "evidence", "dsh-memory.README.md")
with open(snap, "a", encoding="utf-8") as fh:
    fh.write("\n<!-- tamper for test -->\n")
import hashlib
raw = open(snap, "rb").read()
mf = os.path.join(sb, "review", "evidence", "manifest.json")
doc = json.load(open(mf, encoding="utf-8"))
for d in doc["documents"]:
    if d["file"] == "dsh-memory.README.md":
        d["sha256"] = hashlib.sha256(raw).hexdigest(); d["bytes"] = len(raw)
json.dump(doc, open(mf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
def _run(script_dir):
    return subprocess.run([PY, "-X", "utf8", os.path.join(script_dir, "scripts", "evidence_check.py"),
                           "--root", sb, "--quiet"], capture_output=True, text=True,
                          encoding="utf-8", cwd=script_dir)
a = _run(_REPO)          # 交付仓脚本 + 沙箱 root
b = _run(sb)             # 沙箱自带脚本 + 同一 root
check('B 两种启动方式 rc 相同（旧实现不同：0 vs 1）', a.returncode == b.returncode,
      f"交付仓脚本 rc={a.returncode} ｜ 沙箱脚本 rc={b.returncode}")
print('— C 合法数据零行为变更 —')
d0 = tempfile.mkdtemp(prefix="ec_ok_")
shutil.copytree(_REPO, d0, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
r = subprocess.run([PY, "-X", "utf8", os.path.join(d0, "scripts", "evidence_check.py"), "--root", d0],
                   capture_output=True, text=True, encoding="utf-8", cwd=d0)
check('C 合法数据仍 rc=0', r.returncode == 0, f"rc={r.returncode}")
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
