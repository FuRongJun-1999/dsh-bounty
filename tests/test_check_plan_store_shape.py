# -*- coding: utf-8 -*-
"""check_plan.issues_from_store：镜像 `issues` **非对象**须 fail-closed（不是崩）"""
import sys, os, json, tempfile, copy
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
    print('[%s] %s%s' % ("OK " if ok else "NG ", name, (" — " + detail) if detail else ""))

import check_plan as cp
print('— A `issues` 非对象 ⇒ ScanError（契约：结构坏 ⇒ 退 1）—')
for label, val in (("数字", 5), ("字符串", "oops"), ("数组", [1]), ("布尔", True)):
    try:
        cp.issues_from_store({"issues": val})
        check(f'A issues={label} ⇒ 抛 ScanError', False, '未抛')
    except cp.ScanError as exc:
        check(f'A issues={label} ⇒ ScanError', True, str(exc)[:52])
    except Exception as exc:
        check(f'A issues={label} ⇒ ScanError', False, f'抛了 {type(exc).__name__}')
print('— B 零行为变更 —')
check('B issues 缺失 ⇒ 空列表（不抛）', cp.issues_from_store({}) == [], '')
check('B issues 为合法对象 ⇒ 正常解析',
      isinstance(cp.issues_from_store({"issues": {}}), list), '')
print('— C 端到端：core(--state) 退 1 而非抛 —')
d = tempfile.mkdtemp()
for label, txt in (('{"issues": 5}', '{"issues": 5}'), ('{"issues": "oops"}', '{"issues": "oops"}')):
    p = os.path.join(d, "s.json")
    open(p, "w", encoding="utf-8").write(txt)
    try:
        rc, out = cp.core(["--dry-run", "--state", p])
        check(f'C --state {label} ⇒ rc=1 ＋ [error]', rc == 1 and "[error]" in out, f'rc={rc}')
    except Exception as exc:
        check(f'C --state {label} ⇒ 不抛', False, f'{type(exc).__name__}')
print('— D 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('D0 形状判据锚点命中', SRC.count("if not isinstance(_issues, dict):") == 1, '')
check('D 旧实现直接 `(store.get("issues") or {}).items()` ⇒ 非对象必抛 AttributeError（已不在源码里）',
      '    for key, rec in sorted((store.get("issues") or {}).items(),' not in SRC, '')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
