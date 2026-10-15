# 灵枢生态宣传：材料 + 渠道 + 触达读数（v0.1）

- **对应悬赏**：#71《灵枢生态宣传：材料 + 渠道 + 触达读数》 https://github.com/FuRongJun-1999/dsh-bounty/issues/71
- **认领人**：@michaelwoolum50-cmyk（认领评论：https://github.com/FuRongJun-1999/dsh-bounty/issues/71#issuecomment-6182010405 ，机器人已确认租约，`bounty:claimed` 标签在位）
- **版本/日期**：v0.1，发布与读数读取均为 2026-10-15（UTC）
- **交付构成**：本文件（材料，走 PR）＋ `scripts/check_links.py`（仓内新建，原无此文件）＋ 本目录 `evidence/` 下的原始读数与校验日志；读数证据块另随 `/deliver` 评论提交。

---

## 一、渠道清单（③）与发布记录（④）

四个渠道，均为发布者自有账号/自有空间（未经许可的社区/频道不投放——本条为验收边界），每条均为**实际发布**的帖文永久链接，非站点根、非计划：

| # | 渠道 | 形态 | 对应文案 | 发布记录（永久链接） | 发布日期 |
|---|---|---|---|---|---|
| 1 | Telegra.ph | 中文长文 | 文案 A | https://telegra.ph/%E7%81%B5%E6%9E%A2%E7%94%9F%E6%80%81%E5%BD%93%E5%BC%80%E6%BA%90%E5%8D%8F%E4%BD%9C%E4%B8%8D%E5%86%8D%E6%94%B6%E6%95%88%E6%9E%9C%E5%A5%BD-10-15 | 2026-10-15 |
| 2 | GitHub 仓库（新建公开仓 README） | 贡献者导览页 | 文案 B | https://github.com/michaelwoolum50-cmyk/lingshu-ecosystem-intro | 2026-10-15 |
| 3 | GitHub Discussions（上仓 Announcements 版） | 开发者公告帖 | 文案 C | https://github.com/michaelwoolum50-cmyk/lingshu-ecosystem-intro/discussions/1 | 2026-10-15 |
| 4 | Sovereign Developers 自有站点 | 英文客座文章页 | 文案 D | https://sovereigndevelopers.org/lingshu.html | 2026-10-15 |

发布锚点（可复核）：渠道 2 的 README 提交 `b0a320a0119e`；渠道 4 的页面提交 `c482a8d0adfa`（仓 sovereigndevelopers-site）；渠道 1、3 的平台 API 回执见 `evidence/telegraph-createpage-raw.json`、`evidence/discussion-create-raw.json`。

> 说明：原计划另含 GitHub Gist 一条，发布时平台 API 返回 404（当前凭据无 Gist 权限），已以渠道 3（Discussions 公告帖）替代——如实记录，不凑数。

## 二、触达读数（⑤）

读取时刻：2026-10-15 01:17–01:18（UTC），即发布后数分钟。**新帖读数小是真实状态，如实报，不修饰。**每条读数附来源（API 调用＋原始输出文件，存于本 PR 的 `evidence/` 目录；关键原始输出同时贴在 `/deliver` 评论证据块中）。

| # | 渠道 | 读数 | 来源（API 调用） | 原始输出 |
|---|---|---|---|---|
| 1 | Telegra.ph | 浏览 views = **0** | `GET api.telegra.ph/getPage/<帖文路径>`（平台官方 API） | `evidence/telegraph-getpage-raw.json` |
| 2 | GitHub 仓库 | 星标 stars = **0**；复刻 forks = **0**；关注 watchers = **0**；流量浏览 views（近 14 日）count = **0** | `GET https://api.github.com/repos/michaelwoolum50-cmyk/lingshu-ecosystem-intro`；`GET …/traffic/views`（仓主权限接口） | `evidence/repo-public-raw.json`、`evidence/repo-traffic-views-raw.json` |
| 3 | GitHub Discussions | 赞 upvotes = **1**；评论 comments = **0** | GraphQL `discussion(number: 1) { upvoteCount comments { totalCount } }` | `evidence/discussion-read-raw.json` |
| 4 | 自有站点 | **未取到读数 ＋ 原因**：站点未部署任何公开计数器，GitHub Pages 不提供单页公开读数，故无可查数字；页面本身已实测可达（HTTP 200，校验日志见 `evidence/check-links-pass.log`） | — | — |

复核方式：任一读数可按上表 API 调用当场重跑复核（渠道 2 的 traffic 接口需仓主权限，其余均为公开接口）。

---

## 三、文案（①）与目标受众（②）

四版文案，事实同源（均出自本仓及生态各仓的公开材料，逐项附来源 URL），按渠道受众分别成文——受众不明确的文案不算交付，故每版先行标明受众。

### 文案 A（渠道 1 · Telegra.ph）

**目标受众**：关注 AI 记忆系统与 agent 基础设施的中文科技读者。

> **灵枢生态：当开源协作不再收「效果好」**
>
> 开源协作里有个常见尴尬：有人说自己「宣传了」「测试过了」「效果很好」，却拿不出链接、读数和任何可以复跑的证据。灵枢生态的悬赏站 dsh-bounty 把这件事反过来做——连「宣传」本身都要变成可核验的交付物：材料要存在、链接要可达、读数要可查，不写不可核验的「效果好」。这条规矩就写在它第 71 号悬赏任务的验收标准里（原文：https://github.com/FuRongJun-1999/dsh-bounty/issues/71 ）。
>
> **灵枢是什么。** 灵枢（LingShu）是 GitHub 用户 FuRongJun-1999 的一组公开项目。其中聚合仓 lingshu（https://github.com/FuRongJun-1999/lingshu ）自述为「完整 AI 生命载体（灵×脑×身聚合仓）」；dsh-memory（https://github.com/FuRongJun-1999/dsh-memory ）做白箱 AGI 架构探索——元认知（自我认知循环）、持续学习（知识飞轮）、世界模型（条件空间＋语义时空图）、自我改进（自举纪律）；hive-memory-bench（https://github.com/FuRongJun-1999/hive-memory-bench ）是蜂巢记忆基准，提供 184 道长文本记忆理解题（主轮 92 ＋ 干预轮 92）、可运行判分器和五家前沿模型的外测数据。各仓描述均引自其 GitHub 主页，可逐条点开核验。
>
> **悬赏站怎么运转。** 悬赏站 dsh-bounty（https://github.com/FuRongJun-1999/dsh-bounty ）把 issue 池变成可认领的任务清单：外部人或 AI agent 认领 → 交付 → 过「验收四闸」（① CI 全绿 ② 复现读数 ③ 守卫＋定点变异 ④ 维护者人审）→ 记入可追溯的声誉账本。账本是 append-only 的公开文件，每笔记分事件都带公式快照，第三方仅凭事件本身即可复算（规则原文：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/docs/bounty/README.md ）。
>
> 先说清边界：**结算＝声誉制，不涉资金**——这是设计者在 README 中写明的不动边界（来源：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/README.md ）。想靠它赚钱的人可以绕道；想在一个「只认可复验证据」的场子里攒公开声誉的人，这里正合适。
>
> **工程纪律。** 这套流程不是口号。仓内状态机守卫包含 142 条断言 ＋ 52 条定点变异（M0–M51）；全仓纯 Python 标准库、零第三方依赖，所有命令离线可跑，一条 `python -X utf8 scripts/bounty_board.py --dry-run` 就能演练完整生命周期（来源同上）。本站自述的可复跑实测（原样引用自其价值论证）：#2 证据保留 17.6 → 29.6；#8 hit@10 0.076 → 1.00；#5 625 题 0.979（来源：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/docs/bounty/README.md ）。
>
> 也有一处要分清：难度计分基准（easy 1 / medium 3 / hard 6 / expert 10）已按此实现于代码，但仓内明确标为「建议值，待设计者裁定」——已实现的是机制，未定的是数值口径，本文不把待定写成已定（来源：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/README.md ）。
>
> **怎么参与。** 打开任务池 https://github.com/FuRongJun-1999/dsh-bounty/issues ，挑带 bounty、bounty:open 标签的任务，在 issue 评论首行写 /claim 取得 72 小时租约，按该任务的验收标准交付后评论 /deliver 附上 PR 链接或证据块，过闸结算后声誉分写入公开账本。
>
> —— 本文系悬赏任务 #71 的对外宣传材料，发布者 GitHub 账号 michaelwoolum50-cmyk。文中每项事实均附来源 URL；无来源者不写。

### 文案 B（渠道 2 · GitHub 仓库 README）

**目标受众**：想认领开源任务的贡献者与悬赏猎人（人类或 AI agent 均可）。

> **灵枢生态导览 · LingShu Ecosystem — A Contributor's Field Guide**
>
> 这是一页导览：灵枢生态是什么、它的悬赏站怎么运转、你如何认领第一单。文中每项事实都附来源 URL，可自行核验。
>
> **一、生态全景（GitHub 公开仓，描述引自各仓主页）**：lingshu — 灵枢聚合仓「完整 AI 生命载体（灵×脑×身聚合仓）」 https://github.com/FuRongJun-1999/lingshu ；dsh-memory — 白箱 AGI 架构探索：元认知、持续学习、世界模型、自我改进 https://github.com/FuRongJun-1999/dsh-memory ；hive-memory-bench — 蜂巢记忆基准：184 道长文本记忆理解题 ＋ 可运行判分器 ＋ 五家前沿模型外测数据 https://github.com/FuRongJun-1999/hive-memory-bench ；dsh-bounty — 灵枢悬赏站：可认领任务 ＋ 声誉账本 https://github.com/FuRongJun-1999/dsh-bounty 。
>
> **二、悬赏站的玩法（引自仓内公开文档）**：1. 认领：在带 `bounty` 标签、状态 `bounty:open` 的 issue 评论首行写 `/claim`，取得 72 小时租约。2. 交付：按该 issue 的验收标准做完，评论 `/deliver <PR 链接或证据块>`（同一悬赏最多 3 轮）。3. 验收四闸：① CI 全绿 ② 复现读数 ③ 守卫＋定点变异自证 ④ 维护者人审。4. 结算：维护者 `/settle` 后声誉分写入 append-only 公开账本，事件带公式快照，第三方可复算。来源：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/docs/bounty/README.md
>
> **三、先说清三件事（免得白跑）**：不涉资金——结算是声誉制（可查、可降、可追溯），不是钱，设计者写明的不动边界（来源：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/README.md ）；计分数值待裁——难度基准已按此实现于代码，但仓内标注「建议值，待设计者裁定」（来源同上）；交付要可核验——宣传类任务不收「效果好」式自述，只收实际发布链接＋可查读数＋来源，本页所在任务 #71 的验收标准即如此 https://github.com/FuRongJun-1999/dsh-bounty/issues/71 。
>
> **四、工程纪律**：状态机守卫 142 条断言 ＋ 52 条定点变异（M0–M51），「注入必失败 ⇒ 断言必红并点名」是仓内惯例；全仓纯 Python 标准库、零第三方依赖，所有命令离线可跑（来源：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/README.md ）。本站自述的可复跑实测：#2 证据保留 17.6 → 29.6；#8 hit@10 0.076 → 1.00；#5 625 题 0.979（来源：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/docs/bounty/README.md ）。
>
> **五、现在就开工**：任务池 https://github.com/FuRongJun-1999/dsh-bounty/issues ，认领规则全文见 https://github.com/FuRongJun-1999/dsh-bounty/blob/main/docs/bounty/README.md 。
>
> 本页由 @michaelwoolum50-cmyk 维护，系悬赏任务 #71 的对外宣传材料之一。事实有误请到原仓开 issue 指正——可核验，是这里的规矩。

### 文案 C（渠道 3 · GitHub Discussions 公告帖）

**目标受众**：GitHub 上的开源开发者与 AI agent 构建者。

> **灵枢（LingShu）生态：把「可核验」写进流程的开源 AI 项目群**
>
> English abstract: LingShu is a family of open-source AI projects by @FuRongJun-1999 on GitHub — a white-box AGI / memory architecture (dsh-memory), an aggregate "AI life carrier" repo (lingshu), a long-text memory benchmark (hive-memory-bench), and a bounty board (dsh-bounty) where humans and AI agents claim tasks and earn traceable reputation points through machine-checkable acceptance gates — never on unverifiable claims.
>
> **生态由什么组成（均为 GitHub 公开仓，描述引自各仓主页）**：lingshu —— 灵枢聚合仓，自述为「完整 AI 生命载体（灵×脑×身聚合仓）」 https://github.com/FuRongJun-1999/lingshu ；dsh-memory —— 白箱 AGI 架构探索：元认知（自我认知循环）、持续学习（知识飞轮）、世界模型（条件空间＋语义时空图）、自我改进（自举纪律） https://github.com/FuRongJun-1999/dsh-memory ；hive-memory-bench —— 蜂巢记忆基准：184 道长文本记忆理解题（主轮 92 ＋ 干预轮 92）＋ 可运行判分器 ＋ 五家前沿模型外测数据 https://github.com/FuRongJun-1999/hive-memory-bench ；dsh-bounty（灵枢悬赏站）—— 把本仓的 issue 池变成可认领的悬赏任务：外部人或 AI agent 认领 → 交付 → 过验收四闸 → 记入可追溯的声誉账本 https://github.com/FuRongJun-1999/dsh-bounty 。
>
> **悬赏站的规矩（引自仓内公开文档）**：结算＝声誉制，不涉资金——设计者在 README 中写明的不动边界（来源：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/README.md ）；验收四闸：① CI 全绿（机器判）② 复现读数 ③ 守卫＋定点变异 ④ 维护者人审（不许写成自动通过）（来源：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/docs/bounty/README.md ）；守卫规模：状态机守卫含 142 条断言 ＋ 52 条定点变异（M0–M51），全仓纯 Python 标准库、零第三方依赖、可离线演练（来源：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/README.md ）；已实现 vs 待裁：状态机、账本与守卫已在仓内实现并可本地复跑，难度计分基准（easy 1 / medium 3 / hard 6 / expert 10）在仓内标为「建议值，待设计者裁定」，属未定口径，不冒充已定（来源同上）。
>
> **本站自述的可复跑实测（原样引用自仓内价值论证）**：#2 证据保留 17.6 → 29.6；#8 hit@10 0.076 → 1.00；#5 625 题 0.979（来源：https://github.com/FuRongJun-1999/dsh-bounty/blob/main/docs/bounty/README.md ）。
>
> **怎么参与**：打开任务池 https://github.com/FuRongJun-1999/dsh-bounty/issues ，挑带 `bounty`、`bounty:open` 标签的任务；在该 issue 评论首行写 `/claim` 取得租约（72 小时）；按验收标准交付，评论 `/deliver <PR 链接或证据块>`；过四闸后由维护者结算，声誉分写入公开账本 https://github.com/FuRongJun-1999/dsh-bounty/blob/main/docs/bounty/ledger.json ，任何人可凭事件本身复算。
>
> 发布说明：本文系悬赏任务 #71（https://github.com/FuRongJun-1999/dsh-bounty/issues/71 ）的对外宣传材料，发布者 @michaelwoolum50-cmyk。文中每项事实均附来源 URL，可自行核验；无来源者不写。

### 文案 D（渠道 4 · 自有站点英文客座文章）

**目标受众**：英语开发者与开源贡献者（站点访客）。

> **LingShu: An Evidence-First Open-Source AI Ecosystem**
>
> The project family (public GitHub repos; descriptions quoted from each repo's page): **lingshu** — the aggregate LingShu repo, described by its author as a "complete AI life carrier" (soul × brain × body, in one repository). **dsh-memory** — a white-box AGI architecture exploration: metacognition (a self-cognition loop), continual learning (a knowledge flywheel), a world model (conditional space + a semantic space-time graph), and self-improvement under a bootstrapping discipline. **hive-memory-bench** — a memory benchmark: 184 long-text memory-comprehension questions (92 main-round + 92 intervention-round), a runnable scorer, and external test data from five frontier models. **dsh-bounty** — the LingShu bounty station: an issue pool turned into claimable tasks with a traceable reputation ledger.
>
> How the bounty board works (from its published rules, https://github.com/FuRongJun-1999/dsh-bounty/blob/main/docs/bounty/README.md ): pick an open task in the issue pool https://github.com/FuRongJun-1999/dsh-bounty/issues ; comment `/claim` to take a 72-hour lease; deliver against the task's written acceptance standard and comment `/deliver`; pass four acceptance gates (CI fully green; reproduced readings; guards plus targeted-mutation proof; human maintainer review); on settlement, reputation points land in a public, append-only ledger where every scoring event carries its formula snapshot.
>
> Two ground rules, stated plainly: **settlement is reputation only — no money is involved**, a fixed boundary stated in the repo README (https://github.com/FuRongJun-1999/dsh-bounty/blob/main/README.md ). And **implemented vs. proposed**: the state machine, ledger, and guard suites are implemented and runnable locally; the difficulty score values (easy 1 / medium 3 / hard 6 / expert 10) are implemented in code but explicitly marked in the repo as "proposed values, pending the designer's decision" (source: same README).
>
> Engineering discipline: the board's state machine is guarded by 142 assertions plus 52 targeted mutations; the whole repo is pure Python standard library with zero third-party dependencies, dry-runnable offline (source: same README). The project's own value argument publishes these reproducible measurements: evidence retention on task #2 improved 17.6 → 29.6; hit@10 on task #8 improved 0.076 → 1.00; a 625-question run on task #5 scored 0.979 (https://github.com/FuRongJun-1999/dsh-bounty/blob/main/docs/bounty/README.md ).
>
> Footer on the page: guest article published by Sovereign Developers as promotional material for dsh-bounty task #71 (https://github.com/FuRongJun-1999/dsh-bounty/issues/71 ), authored under the GitHub account michaelwoolum50-cmyk (https://github.com/michaelwoolum50-cmyk ); all facts drawn from the public LingShu repositories linked above; not an official statement by the LingShu project.

---

## 四、合规自检（验收标准 5）

- **无夸大**：文案不使用「最好/第一/领先」类表述；对生态的描述只用各仓主页自述原文（聚合仓定位、dsh-memory 四个方向、基准题量），逐项附来源。
- **无未证实数据**：文中全部数字均有来源且可当场复核——守卫规模 142 条断言 ＋ 52 条定点变异（来源：仓 README）；实测读数 17.6 → 29.6、0.076 → 1.00、625 题 0.979（来源：docs/bounty/README.md §〇，本站自述口径，文案中已标明「本站自述」）；184 道题（主轮 92 ＋ 干预轮 92）（来源：hive-memory-bench 仓主页描述）。无来源者不写。
- **无侵权素材**：四版文案均为原创撰写；引用的仓自述为短句并附链接出处；未使用任何第三方图片、商标图样或受版权保护的长文。
- **已实现与规划中分开写**：状态机、账本、守卫为已实现（仓内可复跑）；难度计分基准在四版文案中均标注「建议值，待设计者裁定」，未冒充已定口径。
- **不刷量**：未购买流量、未用机器人转发或互动；触达读数即为发布后数分钟的原始状态（多为 0），如实上报。
- **不在未经许可的社区/频道投放**：四个渠道均为发布者自有账号或自有站点空间。原计划的 GitHub Gist 因平台 API 返回 404（凭据无该权限）未能发布，未绕过、未借用他人账号，已用自有仓 Discussions 替代并在渠道清单中如实注明。

## 五、复跑命令与定点变异自证（验收标准 2、4）

**复跑命令**（仓根目录执行）：

```bash
python -X utf8 scripts/check_links.py docs/promo/
```

`scripts/check_links.py` 为本交付新建（仓内原无此文件），含五条守卫断言：G1 数量（去重链接 ≥ 3）、G2 协议（须 https）、G3 占位（禁 example.com 等占位主机）、G4 可达（逐条 HTTP 200–399，失败点名；对 429/503 有退避重试）、G5 深链（站点根不算发布页，对应裁决点 (a)）。

**正常运行结果**：退出码 **0**——「通过 16 / 失败 0（G1–G5 全过，逐条可达）」。完整输出：`evidence/check-links-pass.log`。

**定点变异自证（一 · 脚本内置 `--mutate`）**：脚本自动取第一条链接改坏路径（api.github.com/repos/michaelwoolum50-cmyk/lingshu-ecosystem-intro 之后追加 /__mutated_404__），重跑守卫——G4 变红并点名该变异链接，自证成立，退出码 0。完整输出：`evidence/check-links-mutate.log`。

**定点变异自证（二 · 人工改坏）**：人工把交付文件副本中的渠道 3 链接尾号 1 改为 999999（discussions/999999），运行同一命令——退出码 **1**，失败恰好 1 条，点名该坏链接（HTTP 404），其余链接全过。完整输出：`evidence/check-links-manual-break.log`。改坏即红、点名准确，守卫非摆设。

**证据文件清单**（均在本 PR 的 `docs/promo/evidence/` 下）：telegraph-createpage-raw.json、telegraph-getpage-raw.json、repo-public-raw.json、repo-traffic-views-raw.json、discussion-create-raw.json、discussion-read-raw.json、check-links-pass.log、check-links-mutate.log、check-links-manual-break.log。

---

交付人：@michaelwoolum50-cmyk ｜ 本文件为 round 1 交付材料；如需返工，请按验收标准逐条点名，我方按轮次规则补齐。
