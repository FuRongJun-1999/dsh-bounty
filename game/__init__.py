# -*- coding: utf-8 -*-
"""game —— 一个纯 stdlib、可离线跑、**确定性**的角色扮演回合引擎。

设计目标（对应悬赏 #70 的验收标准）：
  · **可运行**：`python -X utf8 game/run.py --demo` 跑出一段完整回合（起→行动→结算→落痕）。
  · **可测**：`python -X utf8 tests/test_game.py` 逐条断言，末行「通过 N / 失败 0」。
  · **可证伪**：`--mutate` 把每条判据短路，对应断言**必然转红且恰好转红**。
  · **确定性**：零随机数；同输入两次运行逐字节相同。

两个核心判据（守卫件必须覆盖）：
  ① **角色状态一致性** —— `rules.ALLOWED` 是唯一迁移来源；非法迁移抛 `StateError` 并点名；
     不变量：未经治疗迁移不得回血（`check_invariant_no_free_heal`）。
  ② **记忆召回一致性** —— 同一情境**恒**召回同一事实（`Memory.recall` 纯函数式）；
     同一情境写入不同事实抛 `MemoryConflict`（不静默覆盖）。

边界（与悬赏「不做项」一一对应）：
  · 纯 stdlib（`import` 只出现 stdlib 与本包）—— 由守卫件机械断言；
  · 不联网；不读写玩家隐私；不涉资金/内购；
  · 视觉一律用文本 / ASCII。
"""

__all__ = ["rules", "memory", "engine", "run"]
