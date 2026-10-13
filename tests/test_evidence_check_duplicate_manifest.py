# -*- coding: utf-8 -*-
"""evidence_check.manifest_index 对**清单重复 file**须 fail-closed"""
import sys, os, json, tempfile, importlib.util
sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "evidence_check.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{(" — " + detail) if detail else ""}')

import evidence_check as ec
print('— A 重复 file ⇒ ValueError（被覆盖的那条不会被校验）—')
_mk = lambda docs: {"documents": docs}
_a = {"file": "a.txt", "sha256": "0"*64, "bytes": 1}
_b = {"file": "a.txt", "sha256": "1"*64, "bytes": 2}
try:
    ec.manifest_index(_mk([_a, _b])); check('A 重复 file ⇒ 抛 ValueError', False, '未抛')
except ValueError as exc:
    check('A 重复 file ⇒ ValueError', True, str(exc)[:60])
try:
    ec.manifest_index(_mk([_a, _b, {"file": "c.txt", "sha256": "2"*64, "bytes": 3}]))
    check('A 三条中两条重复 ⇒ 仍抛', False, '未抛')
except ValueError:
    check('A 三条中两条重复 ⇒ 仍抛', True, '')
print('— B 零行为变更 —')
check('B 无重复 ⇒ 正常建索引',
      ec.manifest_index(_mk([_a, {"file": "c.txt", "sha256": "2"*64, "bytes": 3}]))
      == {"a.txt": _a, "c.txt": {"file": "c.txt", "sha256": "2"*64, "bytes": 3}}, '')
try:
    ec.manifest_index({}); check('B 空清单 ⇒ 仍抛 ValueError', False, '')
except ValueError:
    check('B 空清单 ⇒ 仍抛 ValueError', True, '')
print('— D 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
check('D0 去重判据锚点命中', SRC.count("        if name in out:") == 1, f'命中 {SRC.count("        if name in out:")} 次')
check('D 旧实现是**覆盖式**建索引（`out[name] = d` 无条件执行）',
      SRC.count("        out[name] = d") == 1, '')
_old = {}
for d in [_a, _b]:
    _old[d["file"]] = d
check('D 覆盖语义下只留最后一条（旧行为）',
      _old["a.txt"]["sha256"] == "1"*64, 'a.txt 只留了后一条 ⇒ 前一条的声明从未被校验')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
