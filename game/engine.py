# -*- coding: utf-8 -*-
"""game.engine —— 回合引擎：**起 → 行动 → 结算 → 落痕**（纯逻辑层：零 IO、零随机）。

确定性口径（验收标准第 5 条）：
  · **不使用任何随机数**（全仓 `import random` 零次——由守卫件机械断言）；
  · `--seed` 只用于**确定性地挑选剧本**：`scenario_index = seed % len(SCENARIOS)`，
    选取结果**写入落痕**。故「同种子 ⇒ 同输出」是**逐字节**成立的，不是概率成立。
"""
from __future__ import annotations

from . import rules        # noqa: F401  (供测试做定点变异时替换锚点)
from .memory import Memory
from .rules import (Character, StateError, check_invariant_no_free_heal)

# ---------------------------------------------------------------- 剧本（确定性）

#: 每个剧本是一串「行动」；顺序固定，无随机分支。
SCENARIOS = (
    ("初次交锋", (
        ("回忆", "酒馆", "老板娘说过：北门夜里不落锁。"),
        ("回忆", "酒馆", "老板娘说过：北门夜里不落锁。"),   # 幂等重复，不产生新落痕
        ("行动", "攻击", None),
        ("回忆", "酒馆", "老板娘说过：北门夜里不落锁。"),   # 召回必须与首次一致
    )),
    ("负伤撤退", (
        ("回忆", "关隘", "守军换防在子时。"),
        ("行动", "攻击", None),
        ("行动", "攻击", None),
        ("行动", "奔跑", None),
    )),
    ("救治回稳", (
        ("回忆", "医馆", "老医者姓沈。"),
        ("行动", "负伤", None),
        ("行动", "救治", None),
        ("回忆", "医馆", "老医者姓沈。"),
    )),
)

#: 行动 → (伤害值, 目标状态或 None)
ACTIONS = {
    "攻击": (30, None),
    "施法": (10, None),
    "奔跑": (20, None),
    "负伤": (70, "重伤"),
    "救治": (0, "清醒"),
}


class RoundLog:
    """一段完整回合的落痕容器（可逐字节打印、可逐位比对）。"""

    def __init__(self, scenario: str, seed: int):
        self.scenario = scenario
        self.seed = seed
        self.lines: list = []

    def add(self, phase: str, text: str) -> None:
        self.lines.append(f"[{phase}] {text}")

    def text(self) -> str:
        return "\n".join(self.lines)

    def digest(self) -> tuple:
        """可比较摘要：确定性判据的落点。"""
        return (self.scenario, self.seed, tuple(self.lines))


def pick_scenario(seed: int):
    """`seed` → 剧本。**确定性纯函数**（同种子恒同剧本），选取结果进落痕。"""
    return SCENARIOS[seed % len(SCENARIOS)]


def enforce_downed(ch, log) -> None:
    """生命值归零 ⇒ 必须落到『倒下』；不得停在中间态。

    这是**单点判据**（守卫件 A6 的定点变异锚点）：抽成函数是为了让"注入必失败 ⇒
    断言必红"能在不改文件的前提下实施——把本函数换成 no-op，A6 必然转红。
    """
    if ch.hp == 0 and ch.state != "倒下":
        if ch.can_transition("倒下"):
            ch.transition("倒下")
            log.add("结算", f"生命值归零 ⇒ 状态强制迁到『{ch.state}』")
        else:
            raise StateError(
                f"违反不变量①：{ch.name} 生命值归零，但『{ch.state}』无法迁到『倒下』")


def run_round(name: str = "旅人", seed: int = 0, hp: int = rules.MAX_HP):
    """跑一段完整回合，返回 `(log, character, memory)`。

    四个阶段各自记账：
      起   —— 声明剧本与初始状态
      行动 —— 逐条行动（含前置判定：倒下不得执行主动行动）
      结算 —— 扣血 / 治疗 / 状态迁移，并在**每次迁移后**判 ① 号不变量
      落痕 —— 写入记忆；幂等重复只记一次
    """
    scenario_name, steps = pick_scenario(seed)
    ch = Character(name, "清醒", hp)
    mem = Memory()
    log = RoundLog(scenario_name, seed)

    # ---------- 起 ----------
    log.add("起", f"剧本『{scenario_name}』（seed={seed}，索引={seed % len(SCENARIOS)}）")
    log.add("起", f"{ch.name} 就位：状态『{ch.state}』，生命值 {ch.hp}")

    # ---------- 行动 / 结算 ----------
    for kind, action, payload in steps:
        if kind == "回忆":
            first = mem.remember(action, payload)
            got = mem.recall(action)
            if got != payload:
                raise StateError(
                    f"违反不变量②：情境『{action}』召回到『{got}』，与写入的『{payload}』不一致")
            log.add("行动", f"回忆『{action}』→『{got}』"
                            f"（{'首次落痕' if first else '幂等，无新落痕'}）")
            continue

        # 主动行动：前置判定（② 号不变量）
        ch.assert_active(action)
        before = ch.snapshot()
        moved = False

        dmg, target = ACTIONS.get(action, (0, None))
        if target is not None:
            ch.transition(target)
            moved = True
        if dmg:
            ch.damage(dmg)
        if action == "救治":
            ch.heal(40)
        after = ch.snapshot()

        # ① 号不变量：未经治疗迁移不得回血（把「本次是否治疗迁移」如实传入）
        healed = moved and (before[1], after[1]) in rules.HEALING
        check_invariant_no_free_heal(before, after, healed)

        log.add("结算", f"{action}：生命值 {before[2]} → {after[2]}，"
                        f"状态『{before[1]}』→『{after[1]}』")

        # 生命值归零 ⇒ 必须落到『倒下』（不得停在中间态）
        enforce_downed(ch, log)

    # ---------- 落痕 ----------
    log.add("落痕", f"记忆 {len(mem.trace())} 条：" +
                    "；".join(f"{k}={v}" for k, v in mem.snapshot()))
    log.add("落痕", f"终态：状态『{ch.state}』，生命值 {ch.hp}")
    return log, ch, mem
