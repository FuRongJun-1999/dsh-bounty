# -*- coding: utf-8 -*-
"""test_check_plan_missing_inputs.py · `check_plan` 的**账本腿输入缺失**守卫

被修处（`scripts/check_plan.py`）：
    `scan()` 与 `core()` 直接调 `bb.load_ledger(path)` —— **它对不存在的路径返回 `[]`**
    （那是「离线演练起点」语义）。对被**显式指定**的审计对象，这个语义是错的：
    会把「账本文件根本不在」伪装成「账本里一条事件都没有」⇒ 每个号都判「缺账本事件」、
    整批假阳性，而且**退出码 0**。

    本件 docstring 承诺：「1 = 账本/快照读不了（结构坏、**缺文件而显式指定**）」
    —— **快照腿与镜像腿都做了这道检查**（`read_json` 先 `isfile`；`read_state` 同），
    唯独账本腿漏了。

本守卫四组：
  A `read_ledger` 是新的单点，缺失 ⇒ `ScanError`（不静默当空）
  B `scan()` / `core()` 都改走它（静态面）
  C 端到端：`core(["--dry-run","--ledger",<不存在>,"--issues",<存在>])` ⇒ 退 **1** 且含 `[error]`
  D **反向证明**：`bb.load_ledger(<不存在>) == []`（旧路径的静默语义，证明本件有判别力）
"""
import sys
import os
import json
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "check_plan.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import check_plan as cp                                              # noqa: E402
import bounty_board as bb                                            # noqa: E402

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


SRC = open(_IMPL, encoding="utf-8").read()
_TMP = tempfile.mkdtemp(prefix="cp_missing_")
_ISSUES = os.path.join(_TMP, "issues.json")
open(_ISSUES, "w", encoding="utf-8", newline="\n").write('{"items": []}\n')
_MISSING = os.path.join(_TMP, "NOPE-ledger.json")

print('— A `read_ledger` 单点 —')
check('A0 已定义 read_ledger', hasattr(cp, "read_ledger"), '')
if hasattr(cp, "read_ledger"):
    try:
        cp.read_ledger(_MISSING)
        _raised = False
    except cp.ScanError:
        _raised = True
    except Exception as exc:                                         # noqa: BLE001
        _raised = False
        print('       （抛了非 ScanError：%s）' % type(exc).__name__)
    check('A 缺失路径 ⇒ ScanError（不静默当空账本）', _raised, '')
    # 存在的真账本仍正常读
    _real = os.path.join(_REPO, "docs", "bounty", "ledger.json")
    check('A 存在的账本仍正常返回事件列表',
          isinstance(cp.read_ledger(_real), list) and len(cp.read_ledger(_real)) > 0,
          '事件 %d 条' % len(cp.read_ledger(_real)))

print('— B 两个调用点都改走单点（静态面）—')
check('B `scan()` 用 read_ledger', "events = read_ledger(ledger_path)" in SRC, '')
check('B `core()` 用 read_ledger', "events = read_ledger(payload[0])" in SRC, '')
check('B 两处都不再直接调 `bb.load_ledger`',
      "bb.load_ledger(" not in SRC.replace("return bb.load_ledger(path)", ""), '')

print('— C 端到端退出码 —')


def _run(argv):
    """直接调 core（不落 subprocess）：返回 (exit_code, text)。"""
    return cp.core(argv)


_rc, _txt = _run(["--dry-run", "--ledger", _MISSING, "--issues", _ISSUES])
check('C 缺账本 ⇒ 退出码 1（旧实现为 0）', _rc == 1, f'rc={_rc}')
check('C 缺账本 ⇒ 输出含 `[error]` 且**不含对账表**',
      "[error]" in _txt and "缺账本事件" not in _txt, _txt.strip().splitlines()[0][:72] if _txt.strip() else '(空)')

_rc2, _txt2 = _run(["--dry-run", "--ledger", _MISSING, "--issues", os.path.join(_TMP, "ALSO-NOPE.json")])
check('C 账本与快照都缺 ⇒ 仍退 1', _rc2 == 1, f'rc={_rc2}')

_real_led = os.path.join(_REPO, "docs", "bounty", "ledger.json")
_rc3, _txt3 = _run(["--dry-run", "--ledger", _real_led, "--issues", _ISSUES])
check('C 两文件都在 ⇒ 退 0（默认非准入模式）', _rc3 == 0, f'rc={_rc3}')

print('— D 反向证明（旧路径的静默语义）—')
check('D `bb.load_ledger(不存在) == []`（正是「静默当空」的来源）',
      bb.load_ledger(_MISSING) == [],
      f'{bb.load_ledger(_MISSING)!r}')
# 旧实现下 core 会退 0 —— 用源码还原验证
_OLD = SRC.replace("            events = read_ledger(payload[0])",
                   "            events = bb.load_ledger(payload[0])", 1)
check('D0 还原旧实现的锚点命中', _OLD != SRC, '')
if _OLD != SRC:
    import importlib.util
    _d = tempfile.mkdtemp(prefix="cp_old2_")
    _p = os.path.join(_d, "cp_old2.py")
    open(_p, "w", encoding="utf-8", newline="\n").write(_OLD)
    _spec = importlib.util.spec_from_file_location("cp_old2", _p)
    _m = importlib.util.module_from_spec(_spec)
    sys.modules["cp_old2"] = _m
    _spec.loader.exec_module(_m)
    _orc, _otxt = _m.core(["--dry-run", "--ledger", _MISSING, "--issues", _ISSUES])
    check('D 旧实现下同一输入**退 0**（漏报）', _orc == 0, f'rc={_orc}')
    check('D 旧实现把 0 事件的空账本当成真账本（输出里没有 [error]）',
          "[error]" not in _otxt, '')

print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
