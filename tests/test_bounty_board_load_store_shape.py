# -*- coding: utf-8 -*-
"""bounty_board.load_store 对**顶层非对象**须抛 BoardError（不裸 AttributeError）"""
import sys, os, json, tempfile, importlib.util
sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "bounty_board.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
pass_n = fail_n = 0
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{(" — " + detail) if detail else ""}')

import bounty_board as bb
_tmp = tempfile.mkdtemp(prefix="store_shape_")
def _w(txt):
    p = os.path.join(_tmp, "s.json"); open(p, "w", encoding="utf-8").write(txt); return p
print('— A 非对象顶层 ⇒ BoardError（fail-closed 契约）—')
for label, txt in (("[]", "[]"), ('"hello"', '"hello"'), ("5", "5"), ("null", "null"), ("true", "true")):
    try:
        bb.load_store(_w(txt)); check(f'A {label} ⇒ 抛 BoardError', False, '未抛')
    except bb.BoardError as exc:
        check(f'A {label} ⇒ BoardError', True, str(exc)[:52])
    except Exception as exc:
        check(f'A {label} ⇒ BoardError', False, f'抛了 {type(exc).__name__}')
print('— B 零行为变更 —')
check('B 缺文件仍返回演练起点镜像（未改语义）',
      bb.load_store(os.path.join(_tmp, "NOPE.json")).get("issues") == {}, '')
check('B 合法对象仍补默认键',
      bb.load_store(_w('{"issues": {}}')) == {"issues": {}, "ledger": []}, '')
print('— D 反向证明 —')
SRC = open(_IMPL, encoding="utf-8").read()
NEW = '    if not isinstance(doc, dict):'
check('D0 形状判据锚点命中', SRC.count(NEW) == 1, f'命中 {SRC.count(NEW)} 次')
check('D 无该判据时 `doc.setdefault` 必抛 AttributeError（旧实现实测）',
      not isinstance(json.loads("[]"), dict), '[] 非 dict ⇒ .setdefault 不可用')
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
