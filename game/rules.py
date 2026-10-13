# -*- coding: utf-8 -*-
"""game.rules —— 角色状态机与不变量（**纯逻辑层**：零 IO、零随机、零第三方）。

核心判据 ①「角色状态一致性（状态迁移无矛盾）」的单一实现点。

设计口径（为什么这样切）：
  · 状态迁移表 `ALLOWED` 是**唯一**的合法性来源——引擎与测试都读它，不各写一套；
  · 非法迁移**一律抛 `StateError` 并点名**（`从『X』不能迁到『Y』`），不静默忽略——
    静默忽略会让"状态不一致"以更难查的形态在下游爆发；
  · 「无矛盾」拆成两条可机械判定的不变量（见 `Invariant`）：
      ① 生命值不得在**未发生治疗事件**的迁移中被抬高；
      ② `倒下` 态不得执行任何**主动行动**。
    两条都可在迁移前后各取一次快照判定，无需读盘、无需时间。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 状态与迁移表

STATES = ("清醒", "疲惫", "重伤", "倒下")

#: 合法迁移表：src -> 允许的 dst 集合（**单点定义**，引擎与测试共用）
#:
#: `倒下` 是**汇聚态**：生命值归零时无论此前处于哪个主动态都必须能落到它。
#: （本仓守卫件 A6 抓到的真实可达路径：`清醒` 且 30 HP 时再挨一次 30 点攻击 ⇒
#: 0 HP 但仍为 `清醒`；若迁移表不允许 `清醒→倒下`，引擎会抛异常而非进入倒下。）
ALLOWED = {
    "清醒": ("疲惫", "重伤", "倒下"),
    "疲惫": ("清醒", "重伤", "倒下"),
    "重伤": ("倒下", "清醒"),
    "倒下": ("清醒",),
}

#: 哪些迁移属于「治疗」（是 ① 号不变量唯一允许抬高生命值的情形）
HEALING = {("重伤", "清醒"), ("倒下", "清醒"), ("疲惫", "清醒")}

#: `倒下` 态禁止的主动行动名（② 号不变量）
DOWNED_FORBIDDEN_ACTIONS = ("攻击", "施法", "奔跑", "游说")

MAX_HP = 100


class StateError(Exception):
    """非法状态迁移 / 违反不变量。消息里必须点名到（状态、行动或数值）。"""


def check_hp_state(name: str, state: str, hp: int) -> None:
    """③ 号不变量：`倒下` ⇔ 生命值为 0（互为充要，**静止态**判定）。

    在构造与每次 `transition()` 落定时判定；`damage()` 之后到 `enforce_downed()`
    之前的结算中间态不在此列（引擎负责在同一结算内收口）。
    """
    if state == "倒下" and hp != 0:
        raise StateError(f"违反不变量③：{name} 状态『倒下』但生命值为 {hp}（倒下须为 0）")
    if state != "倒下" and hp == 0:
        raise StateError(f"违反不变量③：{name} 生命值为 0 但状态为『{state}』（0 血须为『倒下』）")


class Character:
    """角色：状态 + 生命值。所有变更都必须过 `transition()` / `damage()` / `heal()`。"""

    def __init__(self, name: str, state: str = "清醒", hp: int = MAX_HP):
        if state not in STATES:
            raise StateError(f"未知初始状态：{state!r}（合法集合 {STATES}）")
        if not (0 <= hp <= MAX_HP):
            raise StateError(f"初始生命值越界：{hp}（合法区间 0..{MAX_HP}）")
        check_hp_state(name, state, hp)
        self.name = name
        self.state = state
        self.hp = hp

    # ---------------------------------------------------------- 迁移

    def transition(self, dst: str, heal: int = 0) -> None:
        """迁移到 `dst`。非法则抛 `StateError` 并**点名**来源与目标。

        `heal > 0` 时先回血再落定状态——这是**唯一**的回血入口，且只对 `HEALING`
        里的迁移放行（`倒下 → 清醒` 必须带 `heal`，否则会落成 0 血的『清醒』）。
        """
        if dst not in STATES:
            raise StateError(f"未知目标状态：{dst!r}（合法集合 {STATES}）")
        if dst == self.state:
            raise StateError(f"状态未变化：{self.name} 已在『{dst}』——空迁移视为矛盾")
        if dst not in ALLOWED[self.state]:
            raise StateError(
                f"非法迁移：从『{self.state}』不能迁到『{dst}』"
                f"（允许：{'、'.join(ALLOWED[self.state])}）")
        old_hp = self.hp
        if heal:
            self.heal(heal, via=(self.state, dst))
        try:
            check_hp_state(self.name, dst, self.hp)
        except StateError:
            self.hp = old_hp                 # 判定失败 ⇒ 整次迁移不生效（原子）
            raise
        self.state = dst

    def can_transition(self, dst: str) -> bool:
        return dst in ALLOWED.get(self.state, ()) and dst != self.state

    # ---------------------------------------------------------- 数值

    def damage(self, amount: int) -> None:
        """扣血。生命值归零即视为必须已处于/进入 `倒下`（由 `resolve` 统一处置）。"""
        if amount <= 0:
            raise StateError(f"伤害值必须为正：{amount}")
        self.hp = max(0, self.hp - amount)

    def heal(self, amount: int, via: tuple = None) -> None:
        """治疗。**只允许在治疗类迁移中调用**（① 号不变量的落点）。

        `via` 必须是 `HEALING` 里的一条迁移且来源等于当前状态——由 `transition(dst, heal=…)`
        传入；直接调用 `heal(n)` 一律拒绝并点名（宣称即实现，不靠调用方自觉）。
        """
        if via not in HEALING or via[0] != self.state:
            raise StateError(
                f"违反不变量①：{self.name} 在『{self.state}』直接回血 {amount}，"
                f"未经治疗类迁移（via={via!r}；允许："
                f"{'、'.join(f'{a}→{b}' for a, b in sorted(HEALING))}）")
        if amount <= 0:
            raise StateError(f"治疗值必须为正：{amount}")
        self.hp = min(MAX_HP, self.hp + amount)

    # ---------------------------------------------------------- 不变量的判定面

    def assert_active(self, action: str) -> None:
        """② 号不变量：`倒下` 态不得执行主动行动（点名行动名）。"""
        if self.state == "倒下" and action in DOWNED_FORBIDDEN_ACTIONS:
            raise StateError(
                f"『{self.name}』已倒下，不能执行主动行动『{action}』"
                f"（倒下态禁止：{'、'.join(DOWNED_FORBIDDEN_ACTIONS)}）")

    def snapshot(self) -> tuple:
        """可比较的状态快照：同输入同输出 ⇒ 判据可逐位比对。"""
        return (self.name, self.state, self.hp)


def check_invariant_no_free_heal(before: tuple, after: tuple, moved: bool) -> None:
    """① 号不变量：**未经治疗迁移**时生命值不得上升。

    `moved` 表示本次是否实际发生了状态迁移；只有落在 `HEALING` 里的迁移才允许回血。
    """
        # 不变量：after.hp > before.hp 且没有走治疗迁移 ⇒ 矛盾
    if after[2] > before[2] and not moved:
        raise StateError(
            f"违反不变量①：生命值由 {before[2]} 升到 {after[2]}，"
            f"但本次没有任何治疗类迁移（允许回血的迁移："
            f"{'、'.join(f'{a}→{b}' for a, b in sorted(HEALING))}）")
