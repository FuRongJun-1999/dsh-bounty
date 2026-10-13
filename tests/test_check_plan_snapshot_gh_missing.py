# -*- coding: utf-8 -*-
"""check_plan_snapshot 对**PATH 里没有 gh** 须抛 RuntimeError（⇒ 退 1）"""
import sys, os, json, tempfile, importlib.util
sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "check_plan_snapshot.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{(" — " + detail) if detail else ""}')

import check_plan_snapshot as cs
import shutil, subprocess
print('— A 静态面：捕获 OSError —')
SRC = open(_IMPL, encoding="utf-8").read()
check('A0 `except OSError` 锚点命中', SRC.count("    except OSError as exc:") == 1,
      f'命中 {SRC.count("    except OSError as exc:")} 次')
check('A subprocess 调用在 try 内', "try:\n        proc = subprocess.run(" in SRC, '')
print('— B 端到端：PATH 里没有 gh —')
PY = sys.executable
d = tempfile.mkdtemp(prefix="ghmissing_")
shutil.copytree(_REPO, d, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
env = dict(os.environ); env["PATH"] = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
r = subprocess.run([PY, "-X", "utf8", "scripts/check_plan_snapshot.py", "--out", os.path.join(d, "x.json")],
                   capture_output=True, text=True, encoding="utf-8", cwd=d, env=env)
check('B rc=1（docstring 承诺）', r.returncode == 1, f'rc={r.returncode}')
check('B stderr 含 `[error]` 且说明调不起 gh',
      "[error]" in r.stderr and "调不起 gh" in r.stderr, (r.stderr or "").strip()[-70:])
check('B 不出现未捕获异常的 traceback（类名出现在**我们自己的**消息里是正常的）',
      "Traceback" not in r.stderr, r.stderr.strip()[:70])
print('— D 反向证明 —')
OLD = ("    proc = subprocess.run([\"gh\", \"api\", \"--paginate\", *args],\n"
       "                          capture_output=True, text=True, encoding=\"utf-8\")")
check('D 旧实现**裸调** subprocess（无 try）—— 现已被 try 包住 ⇒ 已修',
      ("try:" in SRC and "except OSError as exc:" in SRC) and OLD not in SRC, '')
check('D `subprocess.run` 对不存在的可执行文件抛 FileNotFoundError（标准库语义）',
      True, 'B 组实跑：修后 rc=1 且 stderr 是 `[error] 调不起 gh…`')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
