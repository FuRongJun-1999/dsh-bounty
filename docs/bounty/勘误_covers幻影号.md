# 勘误：账本中 18 个 `covers` 号记错仓（本站不存在，实为 lingshu 编号）

> 发现：round-53（2026-10-15）｜ 复核并收窄：round-54 ｜ 事实固定与本文：round-55（2026-10-16 修表）
> **本文件不改写任何历史账本行、不改写任何 `event_id`、不改动任何已发布分数。** 它只做一件事：把一个已知缺陷暴露给读者。

## 一、结论

- 账本现有 **215 行 / Δ1036**。其中 **8 行**的 `covers` 共含 **18 个号**，这些号在 `FuRongJun-1999/dsh-bounty` **不存在**（issue 与 PR 两个接口均 404）。
- 这 18 个号**全部**能在 `FuRongJun-1999/lingshu` 找到同名实体 ⇒ 定性为「记账时把目标仓的 issue 编号当成本站编号登记」，**不是**「号后来被删除」。
- 涉及分数合计 **Δ33**（占全站 3.2%）。**分数本身不因本勘误变动** —— 受影响工作项的内容与定档均成立，错的只是**溯源编号的命名空间**。
- 根因：`covers` 与 `project` 是两个独立字段，写入侧无交叉校验；裸整数在多仓生态里必然碰撞。

## 二、判据（四路同向，均可复跑）

1. `gh api /repos/FuRongJun-1999/dsh-bounty/issues/<n>` → **404**；
2. `gh api /repos/FuRongJun-1999/dsh-bounty/pulls/<n>` → **404**（排除「其实是 PR 号」）；
3. **编号下界反证**：本站最近 100 条 issue+PR 的最小号是 **#310** ⇒ 83–281 这段从未存在过；
4. `gh search issues -R FuRongJun-1999/dsh-bounty "<n> in:title"` → 空。

另经批次感知复核：这 18 个号**未出现在任何一份维护者回执正文里**（全仓 566 条评论、维护者 460 条、正文 472,254 字符，用带词界正则 `#\s*<n>(?!\d)` 检索）。

## 三、逐行清单

| 账本行 | 事件 id | holder | 登记的 project | Δ | covers 全值 | 本次涉及的错号 |
|---|---|---|---|---|---|---|
| 4 | `evt_2da6cd1138bd` | @Beiwo992 | `memory` | 3 | [105] | #105 |
| 18 | `evt_8702c8eb925a` | @Beiwo992 | `memory` | 3 | [102] | #102 |
| 26 | `evt_b95dffb2e69f` | @Beiwo992 | `bounty_site` | 3 | [83, 84, 90, 91, 100] | #83, #84, #90, #91, #100 |
| 33 | `evt_044a8c677b84` | @momeiji | `bounty_site` | 3 | [157] | #157 |
| 45 | `evt_7bf140c1b320` | @momeiji | `memory` | 6 | [155] | #155 |
| 67 | `evt_50f63f46235b` | @Beiwo992 | `bounty_site` | 6 | [198, 200, 206, 208, 209, 210, 211, 275, 276] | #200, #206, #208, #209, #210, #275, #276 |
| 77 | `evt_111a604aaef3` | @Beiwo992 | `bounty_site` | 3 | [199] | #199 |
| 78 | `evt_a3ec71d69f81` | @Beiwo992 | `bounty_site` | 3 | [207] | #207 |

> 注：第 67 行的 `covers` 含 9 个号，其中 **#198/#211 已被相应回执提及**，故只列其余 7 个入本表。

## 四、这些号的实际归属（lingshu 侧实体，2026-10-16 现拉）

| 错登号 | 本站 | lingshu 状态 | lingshu 标题（即该工作项真正对应的对象） |
|---|---|---|---|
| #83 | 404 | closed | [core/provenance] 显式来源被 gate/novel_prefeed 覆盖，system/tool/fixture 无法往返恢复 |
| #84 | 404 | closed | [tools/coggraph] 固定 --seed 时 R3 入选边仍随 PYTHONHASHSEED 改变，抽检无法复现 |
| #90 | 404 | closed | fix(core): 整层读取返回全部节点，避免锚点集合被截为 50 条 |
| #91 | 404 | closed | fix(core): 支持零时间半径的同刻查询，避免归一化除零 |
| #100 | 404 | open | [tools/coggraph] naming_report 的 Q2/Q3 把「提及者」也算成「被提及」，纯引用型节点被判「已锚定」逃出隔离区 |
| #102 | 404 | closed | fix(tools): naming_report 的 Q2/Q3 只累计被提及方向，纯引用型节点不再被判已锚定（issue #100） |
| #105 | 404 | closed | fix(core): search_content 评分改用并集分母，相关度恢复区分度 |
| #155 | 404 | open | [nn/hex_ortho] 正交残差金字塔对任意输入两层即「100% 解释」：任意两个各向同性核（smooth+laplacian / smooth+co… |
| #157 | 404 | open | [nn/hex_query] _match_score 贪心 first-fit 使分类结论依赖 detections 顺序：同一检出集合 verdict … |
| #199 | 404 | closed | [core/activation] `ActivationEngine` 空查询把全图节点当种子并给满分——静默返回「全部命中」错答 |
| #200 | 404 | open | [core/P1-3 技能] record_action_sequence 用 LIKE 子串认技能：「备份」的步骤被追加进「删除备份」（程序变成 rm -… |
| #206 | 404 | open | [core/self][信任状态×长期门控] update_trust_state 声称「仅记录，不参与决策」，却对 t_total 零值域校验，而 Lon… |
| #207 | 404 | open | [core/衰减] decay_cycle 情境层只处理 importance > min_confidence 的节点：importance ≤ 阈值的情… |
| #208 | 404 | open | [core/飞轮] _note_reuse 每次检索把本轮累计的整个 bucket 重新插入 flywheel_reuse：同轮同节点重复计数；_reuse… |
| #209 | 404 | open | [packaging] requires-python ">=3.10" 与 extras 下界 numpy>=2.3.5 冲突：Python 3.10 上… |
| #210 | 404 | open | [core/遗忘] forget_advisor 三处错误：importance=0.0 被 `or 0.5` 当成 0.5 不归档；「降权」把低于 arc… |
| #275 | 404 | open | [安全修复回归][component_resolver] #156 v2 的组件 finder 在进程级永久接管 15 个通用模块名（vision / bo… |
| #276 | 404 | open | [tools/coggraph] viewer_serve 的 node_detail 未做包含性校验：path 里的 ../ 可逃出 MDCG_ROOT … |


## 五、影响面与处置口径

- **不动的部分**：8 行的 `delta`／`difficulty`／`impact`／`holder`／`day`／`reason`／`formula` **逐字不变**；全站 Δ1036 不变；贡献表、看板、价值向量、荣誉榜数值均不变。
- **为什么不就地改号**：`event_id = sha1(除 id 外全字段)` ⇒ 改 `covers` 必换 id ⇒ 牵动历史行与全部外发回执，违反 append-only。是否重写属对外账本口径，须由维护者一侧裁定；**本勘误采取的是最小侵入方案**。
- **防复发**：结算脚本写入 `covers` 前应对每个号做一次 `gh api /issues/<n>` 存在性校验，404 即拒绝入账并要求带仓限定写法（如 `lingshu#276`）。此项与本仓既有的「`project` 须由 `target` 派生」同族。

## 六、过程留痕（含两次自我更正）

- round-53 首次报出「22 个幻影号」，但同时给出「11 件零回执」的**错误**结论 —— 该结论用的是一支未自检的探针（按 issue 逐个查评论数）。
- round-54 推翻之：`#270`/`#271` 由 `#269` 的**批次回执**统一裁决（正文逐字「#269 / #270 / #271 三件均已修复并合并」），其自身评论为 0 并不代表漏报；并把 `evt_3ce9acc8812a` 从幻影名单中移除。
- round-55 以带词界的全站回执正文检索固定最终数字：**18 个号 / 8 行 / Δ33**。
- round-56 修本文件自身的一处格式缺陷：第四节 10 行的状态列曾因「先截断后解析」显示为原始 JSON —— 一篇讲数据完整性的勘误必须自身干净。
