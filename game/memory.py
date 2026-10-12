# -*- coding: utf-8 -*-
"""game.memory —— 情境记忆（**纯逻辑层**：零 IO、零随机、零第三方）。

核心判据 ②「记忆召回（同一情境召回同一事实）」的单一实现点。

设计口径：
  · 记忆以 **情境为键、事实为值**；`recall(situation)` 必须是**纯函数式**的——
    同一情境、同一世界状态下，任意次召回**逐位相同**（这是可机械复核的判据，
    不是"感觉上稳定"）；
  · **同一情境写入不同事实 = 冲突**，一律抛 `MemoryConflict` 并点名三样东西
    （情境、旧事实、新事实）。**不静默覆盖**——静默覆盖正是"同一情境召回到不同事实"
    这一矛盾的来源；
  · 重复写入**同一**事实是幂等的（不报错、不产生新的落痕），因为剧情重述同一件事
    是正常行为。
"""
from __future__ import annotations


class MemoryConflict(Exception):
    """同一情境被写入不同事实。消息必须点名情境与两个事实。"""


class Memory:
    """情境 → 事实。冲突即拒，重复即幂等。"""

    def __init__(self):
        self._facts: dict = {}
        self._trace: list = []          # 落痕：每次**首次**写入记一条（幂等不重复记）

    # ---------------------------------------------------------- 写入

    def remember(self, situation: str, fact: str) -> bool:
        """记住「情境 → 事实」。

        返回 `True` 表示**首次**写入（产生落痕），`False` 表示幂等重复（无新落痕）。
        情境已有**不同**事实 ⇒ 抛 `MemoryConflict`（点名情境与两个事实）。
        """
        if not situation:
            raise ValueError("情境不得为空")
        if not fact:
            raise ValueError("事实不得为空")
        old = self._facts.get(situation)
        if old is not None and old != fact:
            raise MemoryConflict(
                f"情境『{situation}』已有事实『{old}』，不能再记住『{fact}』"
                f"——同一情境不得对应多个事实")
        if old == fact:
            return False
        self._facts[situation] = fact
        self._trace.append((situation, fact))
        return True

    # ---------------------------------------------------------- 读取

    def recall(self, situation: str):
        """召回该情境的事实；未知情境返回 `None`（**不猜测**，不回落默认值）。"""
        return self._facts.get(situation)

    def recall_or(self, situation: str, default: str) -> str:
        """带缺省值的召回。缺省只在**确实没有**该情境时生效。"""
        got = self._facts.get(situation)
        return default if got is None else got

    # ---------------------------------------------------------- 判据面

    def is_consistent(self) -> bool:
        """一致性自检：每个情境恰好对应一个事实（结构上恒真，用于反面证明）。"""
        return all(isinstance(k, str) and isinstance(v, str)
                   for k, v in self._facts.items())

    def trace(self) -> tuple:
        """落痕（只增不减、幂等写入不重复记）——确定性比对用。"""
        return tuple(self._trace)

    def snapshot(self) -> tuple:
        """按情境名排序的可比较快照：同输入同输出。"""
        return tuple(sorted(self._facts.items()))
