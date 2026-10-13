# -*- coding: utf-8 -*-
"""evidence_probe 对**版本面快照顶层非对象**须抛 ValueError（⇒ rc 2）"""
import sys, os, json, tempfile, importlib.util
sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "evidence_probe.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{(" — " + detail) if detail else ""}')

import evidence_probe as ep
import shutil, subprocess
print('— A 静态面：形状判据在位 —')
SRC = open(_IMPL, encoding="utf-8").read()
NEW = '    if not isinstance(vdoc, dict):'
check('A0 版本面形状判据锚点命中', SRC.count(NEW) == 1, f'命中 {SRC.count(NEW)} 次')
check('A 判据在 `json.loads` 之后、`.get("version")` 之前',
      SRC.index("vdoc = json.loads(vtext)") < SRC.index(NEW) < SRC.index('vgot = str(vdoc.get("version")'), '')
print('— B 端到端：沙箱里把快照改成非对象 —')
PY = sys.executable
for label, txt in (("[]", "[]"), ('"x"', '"x"'), ("null", "null")):
    d = tempfile.mkdtemp(prefix="probe_shape_")
    shutil.copytree(_REPO, d, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    open(os.path.join(d, "review", "evidence", "dsh-memory.package.json"), "w",
         encoding="utf-8").write(txt)
    r = subprocess.run([PY, "-X", "utf8", "scripts/evidence_probe.py", "record.dsh-memory"],
                       capture_output=True, text=True, encoding="utf-8", cwd=d)
    check(f'B 快照={label} ⇒ rc=2（契约值）', r.returncode == 2, f'rc={r.returncode}')
    check(f'B 快照={label} ⇒ 输出含「顶层不是对象」', "顶层不是对象" in (r.stdout + r.stderr),
          (r.stdout + r.stderr).strip()[-60:])
    check(f'B 快照={label} ⇒ 不崩栈', "Traceback" not in r.stderr, '')
print('— C 零行为变更 —')
d = tempfile.mkdtemp(prefix="probe_ok_")
shutil.copytree(_REPO, d, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
r = subprocess.run([PY, "-X", "utf8", "scripts/evidence_probe.py", "--all"],
                   capture_output=True, text=True, encoding="utf-8", cwd=d)
check('C 现有合法数据仍 rc=0', r.returncode == 0, f'rc={r.returncode}')
print('— D 反向证明 —')
check('D 旧实现直接 `vdoc.get(...)` ⇒ 非对象必抛 AttributeError',
      "if not isinstance(vdoc, dict):" not in SRC.replace(NEW, "", 1), '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
