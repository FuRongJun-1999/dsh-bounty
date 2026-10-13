# -*- coding: utf-8 -*-
"""test_check_plan_ledger_to.py · `check_plan.ledger_states` 的**账本态真源**守卫

被修处（`scripts/check_plan.py`）：
    旧实现**无条件**用本地表 `LEDGER_TO_STATE[action]` 反推账本态 —— 而 **同一个 action 的
    目标态可以不同**：`bounty_board._accept` 在每条通过事件里都写死 `from`/`to`，
    `/verify pass` ⇒ `to=verified`，**`/verify fail` ⇒ `to=claimed`**（退回返工）。

    ⇒ 一次**正常的返工**会被判成 `verified`，与标签/标记的 `claimed` 对不上
      ⇒ **假「态冲突」**，`--check` / `--strict` 直接红。

    修法：`to` **优先**（真源），只在事件**不含 `to`** 时回落到动作表 —— 后者是历史遗留
    的兼容路径（维护者的批量补记件不走 `_accept`，故无 `to`；本仓现有 59 条 `settle`
    全部无 `to`，纯读 `to` 会让它们全丢态、刷出满屏假「缺账本事件」）。

本守卫四组：
  A `to` 优先：`/verify fail`（to=claimed）⇒ `claimed`；`/verify pass`（to=verified）⇒ `verified`
  B 兼容回落：无 `to` 的事件仍按动作表给态（现有 59 条的形态）
  C 假冲突消除：`reconcile` 对「标签=claimed、账本 to=claimed」判**一致**
  D **反向证明**：用**旧实现**（无条件动作表）跑同一套 ⇒ 必须**误报态冲突**
"""
import sys
import os
import re
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


def _ev(ts, issue, action, frm, to=None, actor="alice", **kw):
    e = {"ts": ts, "issue": issue, "action": action, "from": frm, "actor": actor}
    if to is not None:
        e["to"] = to
    e.update(kw)
    return e


# 真源形态：状态机在 `/verify fail` 时写 `to="claimed"`
EV_FAIL = [_ev("2026-10-13T00:00:00Z", 71, "claim", "open", "claimed"),
           _ev("2026-10-13T01:00:00Z", 71, "deliver", "claimed", "delivered"),
           _ev("2026-10-13T02:00:00Z", 71, "verify", "delivered", "claimed", actor="m")]
EV_PASS = [EV_FAIL[0], EV_FAIL[1], {**EV_FAIL[2], "to": "verified"}]
# 兼容形态：维护者批量补记的 settle（现有 59 条的形态，**无 to**）
EV_LEGACY = [{"ts": "2026-10-13T00:00:00Z", "issue": 9, "action": "settle", "actor": "m"}]

print('— A `to` 优先（真源）—')
_a = cp.ledger_states(EV_FAIL)
_b = cp.ledger_states(EV_PASS)
check('A /verify fail（to=claimed）⇒ 账本态 = claimed', _a.get(71) == "claimed", f'{_a}')
check('A /verify pass（to=verified）⇒ 账本态 = verified', _b.get(71) == "verified", f'{_b}')
check('A 同一 action（verify）能映到两种态（旧实现不可能）',
      _a.get(71) != _b.get(71), f'fail={_a.get(71)} pass={_b.get(71)}')

print('— B 兼容回落（无 to 的旧账本件）—')
_c = cp.ledger_states(EV_LEGACY)
check('B 无 to 的 settle 仍按动作表给态 = settled', _c.get(9) == "settled", f'{_c}')

print('— C 假冲突消除 —')
_rep = cp.reconcile([(71, ("bounty", "difficulty:hard", "bounty:claimed"), ())], EV_FAIL)
check('C reconcile 判「一致」（不再假报态冲突）',
      not _rep["defects"]["态冲突"],
      f'{_rep["rows"]} ｜ 态冲突={_rep["defects"]["态冲突"]}')
check('C 账本态与标签态都读到 claimed',
      _rep["rows"] and _rep["rows"][0][1] == "claimed" and _rep["rows"][0][2] == "claimed",
      f'{_rep["rows"][0] if _rep["rows"] else None}')

print('— D 反向证明（旧实现：无条件用动作表）—')
SRC = open(_IMPL, encoding="utf-8").read()
_OLD = SRC.replace(
    "        # ★本笔：`to` 优先（真源）——旧实现无条件用 `LEDGER_TO_STATE` 反推，会把\n"
    "        # `/verify fail`（`to=claimed`）误判成 `verified` ⇒ 假「态冲突」。\n"
    "        to = state_of_event(ev)",
    "        to = LEDGER_TO_STATE.get(str(ev.get(\"action\") or \"\"))", 1)
check('D0 还原旧实现的锚点命中', _OLD != SRC, '')
if _OLD != SRC:
    _d = tempfile.mkdtemp(prefix="cp_old_")
    _p = os.path.join(_d, "cp_old.py")
    open(_p, "w", encoding="utf-8", newline="\n").write(_OLD)
    _spec = importlib.util.spec_from_file_location("cp_old", _p)
    _m = importlib.util.module_from_spec(_spec)
    sys.modules["cp_old"] = _m
    _spec.loader.exec_module(_m)
    _old_states = _m.ledger_states(EV_FAIL)
    _old_rep = _m.reconcile([(71, ("bounty", "difficulty:hard", "bounty:claimed"), ())], EV_FAIL)
    check('D 旧实现把 /verify fail 误判成 verified', _old_states.get(71) == "verified",
          f'{_old_states}')
    check('D 旧实现**误报态冲突**（证明本守卫有判别力）',
          bool(_old_rep["defects"]["态冲突"]),
          f'{_old_rep["defects"]["态冲突"]}')

print('— E 静态面 —')
check('E 新增 `state_of_event` 单点（两处调用同尺子）',
      hasattr(cp, "state_of_event")
      and SRC.count("state_of_event(ev)") >= 2, f'调用 {SRC.count("state_of_event(ev)")} 处')
check('E `ledger_states` 与 `ledger_issue_numbers` 均不再直接用动作表判态',
      "to = LEDGER_TO_STATE.get" not in SRC
      and "if not LEDGER_TO_STATE.get(str(ev.get" not in SRC, '')

print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
