# -*- coding: utf-8 -*-
"""test_daily_table_missing_inputs.py · `daily_table` 的**账本腿输入缺失**守卫

被修处（`scripts/daily_table.py`）：`main()` 直接调 `load_ledger(path)` —— **它对不存在的
路径返回 `[]`**（那是「离线演练起点」语义；`bounty_board.load_ledger` 同款，且被
`test_check_plan_missing_inputs.py` 的 D 组当作**反向证明锚点**，故本笔**不动那个函数**）。
对**闸门**用途这个语义是错的：会把「账本文件根本不在」伪装成「账本里一条事件都没有」
⇒ `--check` 打印「确定性自检通过（账本 0 条事件）」并 **退 0**。

修前实测（纯净 `origin/main`，两条路径都静默绿）：
  ① `daily_table.py --check --ledger <不存在>` ⇒ `rc=0`
  ② **换 CWD** 使默认相对路径 `docs/bounty/ledger.json` 失效 ⇒ `rc=0`（最现实的陷阱：
     任何从别的目录调起这道闸的 CI/hook 都会拿到「检查过、且通过」的绿灯，而它
     **一个对象都没检查**——纪律「0 检查 ≠ 通过」）

同一缺陷族维护者已在 `check_plan.py` 账本腿修过（`read_ledger` 单点 + 显式缺失报错），
本件把同一条规矩补到**同族漏网的第二个调用点**。

本守卫四组（体例对齐 `tests/test_check_plan_missing_inputs.py`）：
  A `read_ledger` 是新的单点，缺失 ⇒ `DailyTableError`（不静默当空）；真账本仍可读；
    `load_ledger` 的旧语义**保留**（供离线演练）
  B `main()` 改走它（静态面）
  C 端到端：显式缺账本 / 生成模式缺账本 / 换 CWD ⇒ 退 **1**；真账本 ⇒ 退 **0**
  D **反向证明**：还原旧实现 ⇒ 同一输入（显式缺失、换 CWD）都**退 0**（漏报）
"""
import importlib.util
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "daily_table.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import daily_table as dt                                              # noqa: E402

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


SRC = open(_IMPL, encoding="utf-8").read()
_TMP = tempfile.mkdtemp(prefix="dt_missing_")
_MISSING = os.path.join(_TMP, "NOPE-ledger.json")
_REAL = os.path.join(_REPO, "docs", "bounty", "ledger.json")
_CWD0 = os.getcwd()

print('— A `read_ledger` 单点 —')
check('A0 已定义 read_ledger', hasattr(dt, "read_ledger"), '')
if hasattr(dt, "read_ledger"):
    try:
        dt.read_ledger(_MISSING)
        _raised = False
    except dt.DailyTableError:
        _raised = True
    except Exception as exc:                                          # noqa: BLE001
        _raised = False
        print('       （抛了非 DailyTableError：%s）' % type(exc).__name__)
    check('A 缺失路径 ⇒ DailyTableError（不静默当空账本）', _raised, '')
    check('A 存在的账本仍正常返回事件列表',
          isinstance(dt.read_ledger(_REAL), list) and len(dt.read_ledger(_REAL)) > 0,
          '事件 %d 条' % len(dt.read_ledger(_REAL)))
    check('A `load_ledger` 旧语义**保留**（缺失 ⇒ []，供离线演练起点）',
          dt.load_ledger(_MISSING) == [], repr(dt.load_ledger(_MISSING)))

print('— B 调用点改走单点（静态面）—')
check('B `main()` 用 read_ledger', "events = read_ledger(args.ledger)" in SRC, '')
check('B `main()` 不再直接调 load_ledger',
      "events = load_ledger(args.ledger)" not in SRC, '')

print('— C 端到端退出码 —')
_rc_check = dt.main(["--check", "--ledger", _MISSING])
check('C 显式缺账本 ⇒ 退 1（旧实现为 0）', _rc_check == 1, f'rc={_rc_check}')
_rc_gen = dt.main(["--ledger", _MISSING])
check('C 生成模式缺账本 ⇒ 退 1（旧实现为 0）', _rc_gen == 1, f'rc={_rc_gen}')
_rc_real = dt.main(["--check", "--ledger", _REAL])
check('C 真账本 ⇒ 退 0', _rc_real == 0, f'rc={_rc_real}')

os.chdir(_TMP)
try:
    _rc_cwd = dt.main(["--check"])            # 默认相对路径在此 CWD 下不存在
finally:
    os.chdir(_CWD0)
check('C 换 CWD 使默认相对路径失效 ⇒ 退 1（旧实现为 0，最现实的陷阱）',
      _rc_cwd == 1, f'rc={_rc_cwd}')

print('— D 反向证明（旧实现的静默语义）—')
_OLD = SRC.replace("        events = read_ledger(args.ledger)",
                   "        events = load_ledger(args.ledger)", 1)
check('D0 还原旧实现的锚点命中', _OLD != SRC, '')
if _OLD != SRC:
    _d = tempfile.mkdtemp(prefix="dt_old_")
    _p = os.path.join(_d, "dt_old.py")
    open(_p, "w", encoding="utf-8", newline="\n").write(_OLD)
    _spec = importlib.util.spec_from_file_location("dt_old", _p)
    _m = importlib.util.module_from_spec(_spec)
    sys.modules["dt_old"] = _m
    _spec.loader.exec_module(_m)
    check('D 旧实现下显式缺账本**退 0**（漏报）',
          _m.main(["--check", "--ledger", _MISSING]) == 0, '')
    os.chdir(_TMP)
    try:
        _old_cwd_rc = _m.main(["--check"])
    finally:
        os.chdir(_CWD0)
    check('D 旧实现下换 CWD 也**退 0**（把「文件不在」当「0 条事件」放过）',
          _old_cwd_rc == 0, f'rc={_old_cwd_rc}')

print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
