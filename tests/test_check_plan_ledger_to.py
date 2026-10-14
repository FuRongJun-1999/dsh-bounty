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

本守卫八组：
  A `to` 优先：`/verify fail`（to=claimed）⇒ `claimed`；`/verify pass`（to=verified）⇒ `verified`
  B 兼容回落：无 `to` 的事件仍按动作表给态（现有 59 条的形态）
  C 假冲突消除：`reconcile` 对「标签=claimed、账本 to=claimed」判**一致**
  D **反向证明**：用**旧实现**（无条件动作表）跑同一套 ⇒ 必须**误报态冲突**
  E 静态面：判据单点、旧写法已不在源码里
  F **非迁移事件恒不迁移态**：`reject` / `role` / `lose` **带 `to`** 时也不得覆盖账本态
    （旧实现只看 `to` 在不在 ⇒ 被拒的命令成了「态迁移」、落选分把定标态读回 `contest`）
  G 端到端：非迁移事件不得抹掉「态冲突」/「缺账本事件」（`--strict` 不得由 1 变 0）
  H **反向证明（本笔）**：把新增的非迁移判据从源码里摘掉 ⇒ F / G 必须复现缺陷
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

print('— F 非迁移事件（**带 `to`**）恒不迁移态 —')
# 真源形态：`bounty_board._decide` 的拒绝事件写 `from == to == 当时态`（:681）；
# `_do_select` 的落选分同形（:914）。这两处的 `to` 是「**当时**的态」，不是迁移目标 ——
# 而 `state_of_event` 只看 `to` 在不在，于是「被拒的命令」与「落选分」都成了态迁移。
EV_REJECT_TO = [_ev("2026-10-13T00:00:00Z", 71, "claim", "open", "claimed"),
                _ev("2026-10-13T01:00:00Z", 71, "settle", "verified", "settled", actor="m"),
                # 有人评论一条会被拒的 /claim：当时 issue 面仍是 delivered ⇒ to=delivered
                _ev("2026-10-13T02:00:00Z", 71, "reject", "delivered", "delivered", actor="mallory")]
EV_LOSE = [_ev("2026-10-13T00:00:00Z", 501, "bid", "open", "contest"),
           _ev("2026-10-13T01:00:00Z", 501, "select", "contest", "delivered", actor="m"),
           # 落选定标：落选分与定标事件**同 ts**、排在其后（`_do_select` 的 extra_events）
           _ev("2026-10-13T01:00:00Z", 501, "lose", "contest", "contest", actor="bob")]
EV_REJECT_ONLY = [_ev("2026-10-13T00:00:00Z", 900, "reject", "verified", "verified", actor="mallory")]
EV_ROLE_TO = [_ev("2026-10-13T00:00:00Z", 901, "claim", "open", "claimed"),
              # 规格 §二：「role 不改态」是**语义**规定 —— 即便该事件带了 `to`（写的是当时态），
              # 也不得被当作迁移目标
              _ev("2026-10-13T01:00:00Z", 901, "role", "delivered", "delivered", role="reviewer")]

check('F 拒绝事件带 `to` 也不覆盖账本态（真态 settled 仍是 settled）',
      cp.ledger_states(EV_REJECT_TO).get(71) == "settled", f'{cp.ledger_states(EV_REJECT_TO)}')
check('F 落选分带 `to` 也不算态迁移（定标后仍读 delivered，不读回 contest）',
      cp.ledger_states(EV_LOSE).get(501) == "delivered", f'{cp.ledger_states(EV_LOSE)}')
check('F role 事件带 `to` 也不算态迁移',
      cp.ledger_states(EV_ROLE_TO).get(901) == "claimed", f'{cp.ledger_states(EV_ROLE_TO)}')
check('F 只有拒绝事件的号 ⇒ 不算「有账本记录」',
      900 not in cp.ledger_issue_numbers(EV_REJECT_ONLY), f'{cp.ledger_issue_numbers(EV_REJECT_ONLY)}')

print('— G 端到端：非迁移事件不得抹掉漂移（`--strict` 不得由 1 变 0）—')
_LBL71 = [(71, ("bounty", "difficulty:hard", "bounty:delivered"), ())]
_rep_b = cp.reconcile(_LBL71, EV_REJECT_TO[:-1])
_rep_a = cp.reconcile(_LBL71, EV_REJECT_TO)
check('G 拒绝事件进账本前：「态冲突」照报',
      bool(_rep_b["defects"]["态冲突"]), f'{_rep_b["defects"]["态冲突"]}')
check('G 拒绝事件进账本后：「态冲突」**仍在**（任何能评论的人不得抹掉漂移）',
      bool(_rep_a["defects"]["态冲突"]),
      f'{_rep_a["rows"]} ｜ 态冲突={_rep_a["defects"]["态冲突"]}')
_rep_9 = cp.reconcile([(900, ("bounty", "difficulty:hard", "bounty:verified"), ())], EV_REJECT_ONLY)
check('G 纯拒绝记录的号仍报「缺账本事件」（离线镜像 A′ 段）',
      any(ln.startswith("#900 ") for ln in _rep_9["defects"]["缺账本事件"]),
      f'{_rep_9["defects"]["缺账本事件"]}')

print('— H 反向证明（摘掉本笔的非迁移判据 ⇒ 缺陷必须复现）—')
_NEW = SRC.replace(
    "    if str(ev.get(\"action\") or \"\") in NON_TRANSITION_ACTIONS:\n        return \"\"",
    "    if False:  # MUT 摘掉非迁移判据\n        return \"\"", 1)
check('H0 摘掉非迁移判据的锚点命中', _NEW != SRC, '')
if _NEW != SRC:
    _d2 = tempfile.mkdtemp(prefix="cp_nonev_")
    _p2 = os.path.join(_d2, "cp_nonev.py")
    open(_p2, "w", encoding="utf-8", newline="\n").write(_NEW)
    _s2 = importlib.util.spec_from_file_location("cp_nonev", _p2)
    _m2 = importlib.util.module_from_spec(_s2)
    sys.modules["cp_nonev"] = _m2
    _s2.loader.exec_module(_m2)
    check('H 摘掉后：拒绝事件又把账本态改回 delivered（F 有判别力）',
          _m2.ledger_states(EV_REJECT_TO).get(71) == "delivered", f'{_m2.ledger_states(EV_REJECT_TO)}')
    check('H 摘掉后：落选分又把态读回 contest（F 有判别力）',
          _m2.ledger_states(EV_LOSE).get(501) == "contest", f'{_m2.ledger_states(EV_LOSE)}')
    check('H 摘掉后：G 的「态冲突」被抹掉（G 有判别力）',
          not _m2.reconcile(_LBL71, EV_REJECT_TO)["defects"]["态冲突"], '')
    _h9 = _m2.reconcile([(900, ("bounty", "difficulty:hard", "bounty:verified"), ())], EV_REJECT_ONLY)
    check('H 摘掉后：纯拒绝记录的号不再报「缺账本事件」（G 有判别力）',
          not any(ln.startswith("#900 ") for ln in _h9["defects"]["缺账本事件"]), '')

print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
