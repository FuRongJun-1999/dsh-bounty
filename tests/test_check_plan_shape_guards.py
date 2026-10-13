# -*- coding: utf-8 -*-
"""test_check_plan_shape_guards.py · `check_plan` 对**畸形输入**不得崩栈（两处）

被修处（`scripts/check_plan.py`）：

  ① `ledger_states` 的**排序键**：旧实现
         key=lambda p: (str((p[1] or {}).get("ts") or ""), p[0])
     `p[1]` 非空但不是 dict（手工改坏的账本里塞了字符串）⇒ `str.get` ⇒
     **未捕获 `AttributeError`**。同函数下方多处已 `isinstance(ev, dict)`，
     **唯独排序键漏了** —— 「过滤在循环里、取键在循环外」的典型漏点。

  ② `read_state` 对**镜像形状**零判据：`load_store` 只保证「文件在、是 JSON」，
     不保证顶层是对象、更不保证 `issues` 是对象。旧实现把 `store.get("issues") or {}`
     直接拿去 `.items()` ⇒ `{"issues": 5}`（**合法 JSON**）抛
     `AttributeError: 'int' object has no attribute 'items'`，`core()` **直接抛**
     而不是返回退出码 —— 而本件 docstring 承诺
     「1 = 账本/快照读不了（**结构坏**、缺文件而显式指定）」。

本守卫四组：
  A ①的非对象元素不再崩
  B ①的合法账本行为不变
  C ②的各坏形状 ⇒ **退 1 ＋ `[error]`**（不抛）；合法镜像仍退 0
  D/E **反向证明**：还原旧实现后，① 抛 `AttributeError`、② 抛 `AttributeError`
"""
import sys
import os
import json
import tempfile
import importlib.util

sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "check_plan.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import check_plan as cp                                              # noqa: E402

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


def _load_old(src, name):
    d = tempfile.mkdtemp(prefix="cp_shape_old_")
    p = os.path.join(d, name + ".py")
    open(p, "w", encoding="utf-8", newline="\n").write(src)
    sp = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


SRC = open(_IMPL, encoding="utf-8").read()

# ---------------------------------------------------------------- A / B（①）
print('— A ① 非对象账本元素不再崩 —')
for label, evs in (("['oops']", ["oops"]),
                   ("[5, None]", [5, None]),
                   ("['oops', 合法事件]",
                    ["oops", {"ts": "2026-10-13T00:00:00Z", "issue": 1, "action": "settle"}]),
                   ("[{'ts': None}, 合法]",
                    [{"ts": None}, {"ts": "2026-10-13T00:00:00Z", "issue": 2, "action": "settle"}])):
    try:
        r = cp.ledger_states(evs)
        check(f'A {label} ⇒ 不抛', True, str(r))
    except Exception as exc:                                         # noqa: BLE001
        check(f'A {label} ⇒ 不抛', False, f'{type(exc).__name__}: {exc}')

print('— B ① 合法账本行为不变 —')
check('B 合法账本仍正常',
      cp.ledger_states([{"ts": "2026-10-13T00:00:00Z", "issue": 9, "action": "settle"}])
      == {9: "settled"}, '')

# ---------------------------------------------------------------- C（②）
print('— C ② 镜像坏形状 ⇒ 退 1 ＋ [error]（不抛）—')


def _core(txt):
    d = tempfile.mkdtemp(prefix="cp_shape_")
    q = os.path.join(d, "s.json")
    open(q, "w", encoding="utf-8").write(txt)
    try:
        return cp.core(["--dry-run", "--state", q]), None
    except Exception as exc:                                         # noqa: BLE001
        return None, exc


for label, txt in (('{"issues": 5}', '{"issues": 5}'),
                   ("[]", "[]"), ('"hello"', '"hello"'), ("null", "null"),
                   ("5", "5"), ('{"ledger": 5}', '{"ledger": 5}')):
    got, exc = _core(txt)
    check(f'C 镜像={label} ⇒ 退 1（不抛）', exc is None and got[0] == 1,
          f'抛 {type(exc).__name__}' if exc else f'rc={got[0]}')
    if exc is None:
        check(f'C 镜像={label} ⇒ 输出含 [error]', "[error]" in got[1],
              got[1].strip().splitlines()[0][:56] if got[1].strip() else "")
check('C 合法镜像仍退 0', _core('{"issues": {}}')[0][0] == 0, '')

# ---------------------------------------------------------------- D / E（反向证明）
print('— D 反向证明：① 旧排序键必抛 —')
_NEW_KEY = ('        key=lambda p: (str((p[1] or {}).get("ts") or "")\n'
            '                       if isinstance(p[1], dict) else "", p[0]),')
_OLD_KEY = '        key=lambda p: (str((p[1] or {}).get("ts") or ""), p[0]),'
check('D0 新排序键锚点命中', SRC.count(_NEW_KEY) == 1, f'命中 {SRC.count(_NEW_KEY)} 次')
if SRC.count(_NEW_KEY) == 1:
    m = _load_old(SRC.replace(_NEW_KEY, _OLD_KEY, 1), "cp_oldkey")
    try:
        m.ledger_states(["oops"])
        check('D 旧实现抛 AttributeError（证明本件有判别力）', False, '未抛')
    except AttributeError as exc:
        check('D 旧实现抛 AttributeError（证明本件有判别力）', True, str(exc)[:52])

print('— E 反向证明：② 旧 read_state 必抛 —')
_NEW_SHAPE = ('    if not isinstance(store, dict):\n'
              '        raise ScanError("状态镜像顶层不是对象：%s（实为 %s）" % (path, type(store).__name__))\n'
              '    if store.get("issues") is not None and not isinstance(store["issues"], dict):\n'
              '        raise ScanError("状态镜像的 issues 不是对象：%s（实为 %s）"\n'
              '                        % (path, type(store["issues"]).__name__))\n'
              '    if store.get("ledger") is not None and not isinstance(store["ledger"], (list, tuple)):\n'
              '        raise ScanError("状态镜像的 ledger 不是数组：%s（实为 %s）"\n'
              '                        % (path, type(store["ledger"]).__name__))\n')
check('E0 形状判据锚点命中', SRC.count(_NEW_SHAPE) == 1, f'命中 {SRC.count(_NEW_SHAPE)} 次')
if SRC.count(_NEW_SHAPE) == 1:
    m2 = _load_old(SRC.replace(_NEW_SHAPE, "", 1), "cp_oldshape")
    d2 = tempfile.mkdtemp(prefix="cp_oldshape_")
    q2 = os.path.join(d2, "s.json")
    open(q2, "w", encoding="utf-8").write('{"issues": 5}')
    try:
        m2.core(["--dry-run", "--state", q2])
        check('E 旧实现抛 AttributeError（证明本件有判别力）', False, '未抛')
    except AttributeError as exc:
        check('E 旧实现抛 AttributeError（证明本件有判别力）', True, str(exc)[:52])

print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
