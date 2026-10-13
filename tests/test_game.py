# -*- coding: utf-8 -*-
"""test_game —— 角色扮演回合引擎守卫（断言 ＋ 定点变异自证）。

对象：`game/`（**纯逻辑层 + CLI 层**：零 IO、零网络、零随机、零第三方）。
悬赏：`FuRongJun-1999/dsh-bounty#70`（难度 hard）· 验收标准见
`docs/bounty/悬赏清单.md` §rp-game。

为什么另立本件：悬赏要求「**可测**」而不是「能演示」——判据不设反面证明就等于没有判据
（本仓惯例：注入必红——把判据短路，断言必转红**并点名**）。故本件 =
①逐条正反断言 ＋ ②每条判据一个**定点变异**（把该判据短路 ⇒ 对应断言**必然转红**且
**恰好**转红，多红=断言语义纠缠、少红=判据空转）。

断言组（与悬赏的验收标准一一对应）：
  [A] 核心判据① · **角色状态一致性**（迁移表单点、非法迁移点名、空迁移、两条不变量）
  [B] 核心判据② · **记忆召回一致性**（同情境恒同事实、冲突不静默覆盖、幂等、未知不猜测）
  [C] **确定性**（同输入同输出、剧本选取为纯函数、全仓零随机数）
  [D] **边界**（悬赏不做项：纯 stdlib、不联网）
  [E] **CLI 正向**（`--demo` 四阶段齐全、同种子逐字节相同、`--list`、用法错误退出码）

用法：
  python -X utf8 tests/test_game.py            # 正向：全断言
  python -X utf8 tests/test_game.py --mutate   # 定点变异自证（逐条恰好转红）
  python -X utf8 tests/test_game.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中期望红项；1 = 有断言失败 / 变异未按预期转红；
        2 = ANCHOR-MISS（变异锚点在实现里命中次数 ≠1——实现漂移即硬失败）。
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # <仓根>/tests
REPO = os.path.dirname(HERE)                               # <仓根>
sys.path.insert(0, REPO)

from game import engine, memory as gmemory, rules, run      # noqa: E402
from game.memory import Memory, MemoryConflict              # noqa: E402
from game.rules import Character, StateError                # noqa: E402

PASS = 0
FAIL = 0
FAILS = []


def ok(name, cond, detail=""):
    """逐条记账：`[PASS]` / `[FAIL] name · detail`（同仓 tests/ 体例）。"""
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


def _catch(fn, *a, **kw):
    """跑 fn，返回 (异常类型名 或 None, 消息)。"""
    try:
        fn(*a, **kw)
        return None, ""
    except Exception as exc:                        # noqa: BLE001
        return type(exc).__name__, str(exc)


# ============================================================ [A] 核心判据①

def a1_transition_table_is_total():
    """A1 迁移表单点且完备：每个状态都在表内，所有目标都是合法状态。"""
    missing = [s for s in rules.STATES if s not in rules.ALLOWED]
    bad = sorted({d for dsts in rules.ALLOWED.values() for d in dsts
                  if d not in rules.STATES})
    return (not missing and not bad), f"缺表项={missing} 越界目标={bad}"


def a2_illegal_transition_raises_and_names():
    """A2 非法迁移必须抛 StateError，且**消息里同时点名来源与目标**。

    非法样例取 `倒下 → 重伤`：`倒下` 只能回 `清醒`（需救治/休整），不得直接转重伤。
    """
    ch = Character("甲", "倒下", 0)
    exc, msg = _catch(ch.transition, "重伤")
    return (exc == "StateError" and "倒下" in msg and "重伤" in msg), \
        f"exc={exc} msg={msg[:70]!r}"


def a3_noop_transition_is_rejected():
    """A3 空迁移（迁到自身）必须被拒，**且被识别为「未变化」这一特定判据**。

    ⚠ 本断言初版只判「抛了 StateError」，结果定点变异 m2（去掉空迁移检查）**零红**
    ——因为 `ALLOWED` 表里没有任何状态把自己列为合法目标，顺带也拦住了，
    于是 A3 看起来绿着、实际**没测到空迁移这条判据**（判据空转）。
    故收紧为：消息必须明确指出「未变化」，而非笼统的「非法迁移」。
    """
    ch = Character("甲", "清醒")
    exc, msg = _catch(ch.transition, "清醒")
    return (exc == "StateError" and "未变化" in msg), \
        f"exc={exc} msg={msg[:70]!r}（须含『未变化』才算命中空迁移判据）"


def a4_invariant_no_free_heal():
    """A4 不变量①：**未经治疗迁移**时生命值不得上升，违者抛 StateError。"""
    before = ("甲", "清醒", 30)
    after = ("甲", "清醒", 90)                      # 回血了，但没有治疗迁移
    exc, msg = _catch(rules.check_invariant_no_free_heal, before, after, False)
    # 反面：确实走了治疗迁移时，同样的数值**不得**报错（否则判据空转/过严）
    exc2, _ = _catch(rules.check_invariant_no_free_heal, before, after, True)
    return (exc == "StateError" and exc2 is None), \
        f"未治疗={exc} 已治疗={exc2} msg={msg[:60]!r}"


def a5_downed_cannot_act_and_names_action():
    """A5 不变量②：`倒下` 态不得执行主动行动，且**消息点名该行动**。"""
    ch = Character("甲", "倒下", 0)
    exc, msg = _catch(ch.assert_active, "攻击")
    exc_ok, _ = _catch(ch.assert_active, "回忆")    # 非主动行动不得被拦（防过严）
    return (exc == "StateError" and "攻击" in msg and exc_ok is None), \
        f"攻击={exc}({msg[:50]!r}) 回忆={exc_ok}"


def a6_zero_hp_must_fall():
    """A6 生命值归零必须落到『倒下』——不得停在中间态。"""
    ch = Character("甲", "清醒", 0)
    log = engine.RoundLog("夹具", 0)
    engine.enforce_downed(ch, log)
    # 反面：未归零者不得被强行迁移
    ch2 = Character("乙", "清醒", 40)
    engine.enforce_downed(ch2, log)
    return (ch.state == "倒下" and ch2.state == "清醒"), \
        f"归零后={ch.state} 未归零后={ch2.state}"


# ============================================================ [B] 核心判据②

def b1_recall_is_keyed_and_stable():
    """B1 同一情境**恒**召回**自己**的事实（多情境夹具：不得张冠李戴、不得抖动）。"""
    m = Memory()
    m.remember("酒馆", "北门夜里不落锁")
    m.remember("关隘", "守军子时换防")
    reps = [m.recall("酒馆") for _ in range(5)]
    return (m.recall("酒馆") == "北门夜里不落锁"
            and m.recall("关隘") == "守军子时换防"
            and len(set(reps)) == 1), \
        f"酒馆={m.recall('酒馆')!r} 关隘={m.recall('关隘')!r} 五次={set(reps)}"


def b2_conflict_not_silently_overwritten():
    """B2 同一情境写入不同事实 ⇒ 抛 MemoryConflict 并**点名情境与两个事实**。"""
    m = Memory()
    m.remember("酒馆", "北门夜里不落锁")
    exc, msg = _catch(m.remember, "酒馆", "北门子时落锁")
    return (exc == "MemoryConflict" and "酒馆" in msg
            and "北门夜里不落锁" in msg and "北门子时落锁" in msg), \
        f"exc={exc} msg={msg[:80]!r}"


def b3_idempotent_write_has_no_new_trace():
    """B3 幂等重复写入同一事实：不报错、**不产生新落痕**。"""
    m = Memory()
    first = m.remember("酒馆", "北门夜里不落锁")
    second = m.remember("酒馆", "北门夜里不落锁")
    return (first is True and second is False and len(m.trace()) == 1), \
        f"first={first} second={second} 落痕={len(m.trace())}"


def b4_unknown_situation_returns_none():
    """B4 未知情境召回返回 `None`——**不猜测**、不回落默认值。"""
    m = Memory()
    m.remember("酒馆", "北门夜里不落锁")
    got = m.recall("从未到过的地方")
    return (got is None), f"got={got!r}"


# ============================================================ [C] 确定性

def c1_same_seed_same_digest():
    """C1 同一进程内跑两次同种子回合：落痕摘要**逐位相同**。"""
    d1 = engine.run_round(seed=1)[0].digest()
    d2 = engine.run_round(seed=1)[0].digest()
    return (d1 == d2), f"d1==d2? {d1 == d2}"


def c2_pick_scenario_is_pure():
    """C2 `pick_scenario` 是纯函数：同种子恒同剧本，且不同种子能选到不同剧本。"""
    same = engine.pick_scenario(7) == engine.pick_scenario(7)
    differ = engine.pick_scenario(0) != engine.pick_scenario(1)
    return (same and differ), f"同种子相同={same} 异种子不同={differ}"


def c3_no_random_anywhere():
    """C3 全仓**零随机数**（验收标准第 5 条的机械判据）。"""
    hits = []
    for dp, dn, fn in os.walk(os.path.join(REPO, "game")):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            for i, ln in enumerate(open(p, encoding="utf-8").read().splitlines(), 1):
                if re.search(r"^\s*(import|from)\s+random\b", ln) or \
                   re.search(r"\brandom\.", ln):
                    hits.append(f"{os.path.relpath(p, REPO)}:{i}")
    return (not hits), f"命中={hits[:4]}"


# ============================================================ [D] 边界

def d1_only_stdlib_and_self():
    """D1 只 import stdlib 与本包（悬赏不做项：不引入第三方依赖）。"""
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    bad = []
    for dp, dn, fn in os.walk(os.path.join(REPO, "game")):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            for i, ln in enumerate(open(p, encoding="utf-8").read().splitlines(), 1):
                m = re.match(r"\s*(?:from|import)\s+([A-Za-z_][\w.]*)", ln)
                if not m:
                    continue
                top = m.group(1).split(".")[0]
                if top in ("game", "__future__") or top in stdlib:
                    continue
                bad.append(f"{os.path.relpath(p, REPO)}:{i} -> {top}")
    return (not bad), f"非 stdlib 导入={bad[:5]}"


def d2_no_network_calls():
    """D2 不联网（无 socket / urllib / http.client / requests）。"""
    bad = []
    for dp, dn, fn in os.walk(os.path.join(REPO, "game")):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            for i, ln in enumerate(open(p, encoding="utf-8").read().splitlines(), 1):
                if re.search(r"\b(socket|urllib|http\.client|requests|httpx)\b", ln):
                    bad.append(f"{os.path.relpath(p, REPO)}:{i}")
    return (not bad), f"命中={bad[:5]}"


# ============================================================ [E] CLI 正向

def _run_main(argv):
    """进程内跑 `game.run.main`，捕获 stdout/stderr 与退出码。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run.main(argv)
    return code, out.getvalue(), err.getvalue()


def e1_demo_covers_four_phases():
    """E1 `--demo` 退出码 0，且输出**四个阶段标记齐全**（起→行动→结算→落痕）。"""
    code, out, _ = _run_main(["--demo", "--seed", "0"])
    marks = [m for m in ("[起]", "[行动]", "[结算]", "[落痕]") if m in out]
    return (code == 0 and len(marks) == 4), f"code={code} 阶段={marks}"


def e2_demo_is_byte_identical():
    """E2 `--demo` 同种子两次运行**逐字节相同**（验收标准第 5 条）。"""
    c1, o1, _ = _run_main(["--demo", "--seed", "2"])
    c2, o2, _ = _run_main(["--demo", "--seed", "2"])
    return (c1 == 0 and c2 == 0 and o1 == o2), f"code={c1}/{c2} 相同={o1 == o2}"


def e3_list_works():
    """E3 `--list` 退出码 0，且列出全部剧本。"""
    code, out, _ = _run_main(["--list"])
    return (code == 0 and all(sc in out for sc, _ in engine.SCENARIOS)), \
        f"code={code} 剧本数={len(engine.SCENARIOS)}"


def e4_usage_error_exit_2():
    """E4 用法错误（非整数 seed / 无参数）退出码为 **2**（与 1=判据失败区分）。"""
    c1, _, _ = _run_main(["--demo", "--seed", "abc"])
    c2, _, _ = _run_main([])
    return (c1 == 2 and c2 == 2), f"坏seed={c1} 无参数={c2}"


# ============================================================ 断言清单

ASSERTIONS = (
    ("A1", "迁移表单点且完备", a1_transition_table_is_total),
    ("A2", "非法迁移抛 StateError 并点名", a2_illegal_transition_raises_and_names),
    ("A3", "空迁移被拒", a3_noop_transition_is_rejected),
    ("A4", "不变量①：未治疗不得回血", a4_invariant_no_free_heal),
    ("A5", "不变量②：倒下不得主动行动", a5_downed_cannot_act_and_names_action),
    ("A6", "生命值归零必落『倒下』", a6_zero_hp_must_fall),
    ("B1", "同情境恒召回自己事实", b1_recall_is_keyed_and_stable),
    ("B2", "冲突不静默覆盖", b2_conflict_not_silently_overwritten),
    ("B3", "幂等写入无新落痕", b3_idempotent_write_has_no_new_trace),
    ("B4", "未知情境不猜测", b4_unknown_situation_returns_none),
    ("C1", "同种子同摘要", c1_same_seed_same_digest),
    ("C2", "剧本选取是纯函数", c2_pick_scenario_is_pure),
    ("C3", "全仓零随机数", c3_no_random_anywhere),
    ("D1", "仅 stdlib 与本包", d1_only_stdlib_and_self),
    ("D2", "不联网", d2_no_network_calls),
    ("E1", "--demo 四阶段齐全", e1_demo_covers_four_phases),
    ("E2", "--demo 逐字节相同", e2_demo_is_byte_identical),
    ("E3", "--list 可用", e3_list_works),
    ("E4", "用法错误退出码 2", e4_usage_error_exit_2),
)


# ============================================================ 定点变异

def _m_set_allowed_clear_allow():
    """m1 放开迁移表：允许 `倒下 → 重伤`（非法一跳变合法）。**必须返回原值**。"""
    orig = tuple(rules.ALLOWED["倒下"])
    rules.ALLOWED["倒下"] = orig + ("重伤",)
    return orig


def _m_restore_allowed(orig):
    rules.ALLOWED["倒下"] = orig


def _m_transition_skip_noop_check():
    """m2 去掉空迁移检查。"""
    orig = Character.transition

    def patched(self, dst):
        if dst not in rules.STATES:
            raise StateError(f"未知目标状态：{dst!r}")
        if dst not in rules.ALLOWED[self.state]:
            raise StateError(f"非法迁移：从『{self.state}』不能迁到『{dst}』")
        self.state = dst
    Character.transition = patched
    return orig


def _m_noop_invariant():
    """m3 让不变量① 空转。"""
    orig = rules.check_invariant_no_free_heal
    rules.check_invariant_no_free_heal = lambda b, a, moved=None: None
    engine.check_invariant_no_free_heal = rules.check_invariant_no_free_heal
    return orig


def _m_noop_assert_active():
    """m4 让不变量② 空转。"""
    orig = Character.assert_active
    Character.assert_active = lambda self, action: None
    return orig


def _m_noop_enforce_downed():
    """m5 让「归零必落倒下」空转。"""
    orig = engine.enforce_downed
    engine.enforce_downed = lambda ch, log: None
    return orig


def _m_recall_jitters():
    """m6 让 recall 对**已知**情境返回抖动值（同情境召回不一致）。

    只抖动已存在的情境键 ⇒ **未知情境仍返回 None**，故 B4 不受牵连（避免判据纠缠）。
    """
    orig = Memory.recall
    counter = {"n": 0}

    def patched(self, situation):
        if situation not in self._facts:
            return None
        counter["n"] += 1
        return f"{self._facts[situation]}#{counter['n']}"
    Memory.recall = patched
    return orig


def _m_recall_cross_keyed():
    """m6b 让 recall 张冠李戴（返回别的情境的事实）。"""
    orig = Memory.recall

    def patched(self, situation):
        if situation not in self._facts:
            return None
        return next(iter(self._facts.values()))
    Memory.recall = patched
    return orig


def _m_remember_overwrites():
    """m7 让冲突静默覆盖（**不再点名**情境与两个事实 ⇒ B2 转红）。"""
    orig = Memory.remember

    def patched(self, situation, fact):
        if not situation or not fact:
            raise ValueError("情境/事实不得为空")
        if self._facts.get(situation) == fact:
            return False
        self._facts[situation] = fact
        self._trace.append((situation, fact))
        return True
    Memory.remember = patched
    return orig


def _m_remember_traces_idempotent():
    """m8 让幂等重复也追加落痕。

    **冲突路径保持原实现**（转调 orig）⇒ 只动 B3，不牵连 B2。
    """
    orig = Memory.remember

    def patched(self, situation, fact):
        old = self._facts.get(situation)
        if old is not None and old != fact:
            return orig(self, situation, fact)       # 冲突路径原样 ⇒ B2 不受影响
        self._facts[situation] = fact
        self._trace.append((situation, fact))        # 幂等也记落痕
        return old is None
    Memory.remember = patched
    return orig


def _m_recall_defaults():
    """m9 让未知情境回落到默认值（猜测）。"""
    orig = Memory.recall
    Memory.recall = lambda self, situation: self._facts.get(situation, "（未知）")
    return orig


def _m_pick_scenario_constant():
    """m10 让剧本选取忽略种子（恒返回第 0 个）。"""
    orig = engine.pick_scenario
    engine.pick_scenario = lambda seed: engine.SCENARIOS[0]
    return orig


def _m_round_not_deterministic():
    """m11 让**引擎**落痕带上进程内计数器（C1 的判据面）。"""
    orig = engine.run_round
    counter = {"n": 0}

    def patched(**kw):
        counter["n"] += 1
        log, ch, mem = orig(**kw)
        log.lines.append(f"[落痕] 内部计数={counter['n']}")
        return log, ch, mem
    engine.run_round = patched
    return orig


def _m_drop_record_phase():
    """m12 让 `--demo` 丢掉『落痕』阶段的标记（E1 的判据面）。

    注意：必须打 **`run.run_round`**——`run.py` 在导入时就绑定了该名字，
    改 `engine.run_round` 对 CLI 无效（这一点由本变异表自证）。
    """
    orig = run.run_round

    def patched(**kw):
        log, ch, mem = orig(**kw)
        log.lines = [ln for ln in log.lines if not ln.startswith("[落痕]")]
        return log, ch, mem
    run.run_round = patched
    return orig


def _m_run_output_not_stable():
    """m13 让 CLI 输出带上渲染序号（E2 的判据面：两次运行不再逐字节相同）。

    只打 `run.run_round` ⇒ 引擎侧的 C1 不受影响（避免纠缠）。
    """
    orig = run.run_round
    counter = {"n": 0}

    def patched(**kw):
        log, ch, mem = orig(**kw)
        counter["n"] += 1
        log.lines.append(f"渲染序号 {counter['n']}")
        return log, ch, mem
    run.run_round = patched
    return orig


#: 变异表：`(编号, 说明, 施加函数, 期望**恰好**转红的断言编号)`
MUTATIONS = (
    ("m1", "放开迁移表（倒下→重伤 合法化）", _m_set_allowed_clear_allow, "A2"),
    ("m2", "去掉空迁移检查", _m_transition_skip_noop_check, "A3"),
    ("m3", "不变量①空转", _m_noop_invariant, "A4"),
    ("m4", "不变量②空转", _m_noop_assert_active, "A5"),
    ("m5", "归零必落倒下 空转", _m_noop_enforce_downed, "A6"),
    ("m6", "recall 张冠李戴（跨情境）", _m_recall_cross_keyed, "B1"),
    ("m7", "冲突静默覆盖（不点名）", _m_remember_overwrites, "B2"),
    ("m8", "幂等写入也记落痕", _m_remember_traces_idempotent, "B3"),
    ("m9", "未知情境回落默认值", _m_recall_defaults, "B4"),
    ("m10", "剧本选取忽略种子", _m_pick_scenario_constant, "C2"),
    ("m11", "引擎落痕带内部计数器", _m_round_not_deterministic, "C1"),
    ("m12", "丢掉『落痕』阶段标记", _m_drop_record_phase, "E1"),
    ("m13", "CLI 输出带渲染序号", _m_run_output_not_stable, "E2"),
)


def _evaluate_all():
    """跑全部断言，返回 (红项编号集合, 逐条明细)。"""
    red = set()
    detail = []
    for num, desc, fn in ASSERTIONS:
        try:
            cond, det = fn()
        except Exception as exc:                     # noqa: BLE001
            cond, det = False, f"异常 {type(exc).__name__}: {exc}"
        if not cond:
            red.add(num)
        detail.append((num, desc, bool(cond), det))
    return red, detail


def run_assertions():
    for num, desc, fn in ASSERTIONS:
        try:
            cond, det = fn()
        except Exception as exc:                     # noqa: BLE001
            cond, det = False, f"异常 {type(exc).__name__}: {exc}"
        ok(f"{num} {desc}", cond, det)


def _restore(name, token):
    """按变异类型复原实现（`token` 一律是施加函数返回的原值）。"""
    if name == "m1":
        _m_restore_allowed(token)
    elif name == "m2":
        Character.transition = token
    elif name == "m3":
        rules.check_invariant_no_free_heal = token
        engine.check_invariant_no_free_heal = token
    elif name == "m4":
        Character.assert_active = token
    elif name == "m5":
        engine.enforce_downed = token
    elif name in ("m6", "m6b", "m9"):
        Memory.recall = token
    elif name in ("m7", "m8"):
        Memory.remember = token
    elif name == "m10":
        engine.pick_scenario = token
    elif name == "m11":
        engine.run_round = token
    elif name in ("m12", "m13"):
        run.run_round = token


def run_mutations():
    """每条变异：施加 ⇒ 断言集**恰好**只有期望那条转红 ⇒ 复原后全绿。"""
    baseline_red, _ = _evaluate_all()
    if baseline_red:
        ok("变异前置：基线必须全绿", False, f"基线红项={sorted(baseline_red)}")
        return
    ok("变异前置：基线全绿", True)

    for name, desc, apply_fn, expect in MUTATIONS:
        token = apply_fn()
        try:
            red, _ = _evaluate_all()
        finally:
            _restore(name, token)
        after_red, _ = _evaluate_all()
        ok(f"{name} {desc} ⇒ 恰好 {expect} 转红", red == {expect},
           f"实际红项={sorted(red)}（期望仅 {expect}）")
        ok(f"{name} 复原后全绿", not after_red, f"残留红项={sorted(after_red)}")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--list" in args:
        print("定点变异表（编号 · 说明 · 期望恰好转红的断言）：")
        for name, desc, _, expect in MUTATIONS:
            print(f"  {name:>4}  {desc:<28} ⇒ {expect}")
        print(f"\n共 {len(MUTATIONS)} 条变异 / {len(ASSERTIONS)} 条断言")
        return 0

    if "--mutate" in args:
        print("== 定点变异自证（注入必红；逐条**恰好**转红）==")
        run_mutations()
    else:
        print("== 正向断言（核心判据① 角色状态一致性 / 判据② 记忆召回一致性）==")
        run_assertions()

    print()
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
