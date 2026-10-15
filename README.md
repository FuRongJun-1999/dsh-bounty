# 灵枢悬赏站 · dsh-bounty

> 把本仓的 issue 池变成**可认领的悬赏任务**：外部人或 AI agent 认领 → 交付 →
> 过**验收四闸** → 记入**可追溯的声誉账本**。
> **结算＝声誉制，不涉资金**（资金与账号是设计者的不动边界）。

设计真源：[`docs/spec/悬赏板设计_v0.1.md`](docs/spec/悬赏板设计_v0.1.md)（v0.1，2026-10-09）。
规则文档：[`docs/bounty/README.md`](docs/bounty/README.md)。

---

## 一、这仓里有什么

| 面 | 件 | 说明 |
|---|---|---|
| 状态机 | [`scripts/bounty_board.py`](scripts/bounty_board.py) | 三层白箱：纯逻辑层／薄 GitHub 客户端（stdlib `urllib`）／路由层；**状态权威面＝issue 线程本身**（评论里的 `<!-- bounty:v1 {…} -->` 标记） |
| 薄壳 | [`.github/workflows/bounty.yml`](.github/workflows/bounty.yml) | 事件只经 `$GITHUB_EVENT_PATH` 文件进 python；`persist-credentials: false`；权限最小面 |
| 发布模板 | [`.github/ISSUE_TEMPLATE/bounty.yml`](.github/ISSUE_TEMPLATE/bounty.yml) | 悬赏发布（验收标准必填） |
| 状态机守卫 | [`tests/test_bounty_board.py`](tests/test_bounty_board.py) | 142 条断言 ＋ 52 条定点变异（M0–M51，含审核员机制 `[R]` 组） |
| **网站面生成器** | [`scripts/build_site.py`](scripts/build_site.py) | 静态站（纯 stdlib）；**荣誉榜由账本机械生成** |
| **网站面守卫** | [`tests/test_build_site.py`](tests/test_build_site.py) | 24 条断言 ＋ 5 条定点变异（N0–N4） |
| 账本／荣誉榜 | [`docs/bounty/ledger.json`](docs/bounty/ledger.json) ／ [`docs/bounty/board.md`](docs/bounty/board.md) | append-only 事件流 ／ 由账本机械生成；**已知勘误：**[`docs/bounty/勘误_covers幻影号.md`](docs/bounty/勘误_covers幻影号.md)（8 行 18 号记错仓，分数不变） |
| **每日贡献表生成器** | [`scripts/daily_table.py`](scripts/daily_table.py) | 从账本按**结算日**渲染贡献表（确定性；`--check` 自检） |
| **每日贡献表守卫** | [`tests/test_daily_table.py`](tests/test_daily_table.py) | 18 条断言 ＋ 5 条定点变异（M1–M5） |
| **账本不变量自审** | [`scripts/check_ledger_invariants.py`](scripts/check_ledger_invariants.py) | **15 项**结构不变量逐项计数（id 可复算／形态／唯一、难度与影响闭集、必填、`covers` 形态、`ts` 形态、**`day == date(ts+8h)`**、公式自洽、项目非空、产物合计对账），非零项**逐条点名**；**不 import `bounty_board`**，id 公式独立重实现（当独立见证者，避免同错同绿） |
| **账本不变量守卫** | [`tests/test_check_ledger_invariants.py`](tests/test_check_ledger_invariants.py) | 13 条断言 ＋ **5 条定点变异**（ts 后移 8 小时／难度填词表外值／删必填／坏 id／产物合计不符——每一条**恰好命中**期望的那一项） |
| 每日贡献表 | [`docs/bounty/贡献表.md`](docs/bounty/贡献表.md) | 由账本机械生成（按结算日分节 ＋ 按人合计 ＋ 累计） |
| **悬赏清单生成器** | [`scripts/bounty_list.py`](scripts/bounty_list.py) | 真源 `docs/bounty/悬赏.json` → 清单 `docs/bounty/悬赏清单.md`（纯 stdlib、确定性；`--check` 自检漂移） |
| **悬赏清单守卫** | [`tests/test_bounty_list.py`](tests/test_bounty_list.py) | 21 条断言 ＋ 17 条定点变异（M1–M17） |
| 悬赏清单 | [`docs/bounty/悬赏清单.md`](docs/bounty/悬赏清单.md) | **统一查看面**：长期方向的验收标准／进度／负责人（由真源机械生成，禁手改） |
| 价值向量 | [`docs/bounty/value_vector.json`](docs/bounty/value_vector.json) | 由账本导出（声誉分 ＋ 难度/影响两轴；**不含金额**） |
| **审核员机制** | [`scripts/bounty_board.py`](scripts/bounty_board.py) ／ [`docs/spec/审核员机制_v0.1.md`](docs/spec/审核员机制_v0.1.md) | 回避闸（自审自结禁止）＋ 审核员档（`/verify` `/appraise`，**不含** `/settle`）＋ 账本 `role` 事件授权面 ＋ 晋升复合判据 |
| 晋升评估／授权面 | [`docs/bounty/promotion.json`](docs/bounty/promotion.json) ／ [`docs/bounty/roles.json`](docs/bounty/roles.json) | 由账本机械导出（`--promotion-out` ／ `--roles-out`；只读、纯函数） |
| 静态站产物 | [`site/`](site/) | `index / board / honor / rules` 四页（由生成器产出） |
| **插件测评站生成器** | [`scripts/review_build.py`](scripts/review_build.py) | 真源 `review/data/plugins.json` → 产物 `review/site/*.html`（6 页：首页／榜单／方法／每插件一页；纯 stdlib、确定性、不触网；`--print` 只打印不落盘、`--check` 漂移闸、坏真源 fail-closed 退出码 2） |
| **插件测评站守卫** | [`tests/test_review_build.py`](tests/test_review_build.py) | 48 条断言 ＋ 14 组定点变异（逐条短路一条映射 ⇒ 期望红项**恰好**命中；锚点缺失 ⇒ 退出码 2 fail-closed） |
| **本机复跑探针** | [`scripts/evidence_probe.py`](scripts/evidence_probe.py) | 具名纯函数、只读已提交快照、确定性 stdout——供证据链「本机复跑」档逐字节复算 |
| **证据链校验件** | [`scripts/evidence_check.py`](scripts/evidence_check.py) | 快照 ←→ 清单 ←→ 真源 三方对账 ＋ `--repro` 逐字节复算（纯 stdlib、只读、不触网） |
| **证据链守卫** | [`tests/test_evidence_check.py`](tests/test_evidence_check.py) | 23 条断言 ＋ 6 组定点变异（含 tamper 反向判据） |
| **CI 门禁** | [`.github/workflows/review-check.yml`](.github/workflows/review-check.yml) | 生成器 ＋ 漂移闸 ＋ 证据链 ＋ 两守卫 ＋ 两组变异自证 ＋**「跑完不许把仓搞脏」**（`git status --porcelain` 必须空） |
| 历史测评数据（#104 保留） | [`review/legacy/dsh-platform-v1/`](review/legacy/dsh-platform-v1/README.md) | PR #104 的三条**平台／运维类**插件测评（真源 schema 与现行引擎不兼容，故**保留不渲染**；见该目录 README 的差异表） |
| **三方对账校验件** | [`scripts/check_plan.py`](scripts/check_plan.py) | issue 标签面 × 标记面 × 账本面 → 一张对账表 ＋ 五类不一致**逐行点名**（纯 stdlib、只读、不触网；输入源 `--state` 镜像 或 `--ledger/--issues`；`--check` 漂移检测、`--strict` 准入、`--json` 机读） |
| **三方对账守卫** | [`tests/test_check_plan.py`](tests/test_check_plan.py) | 48 条断言 ＋ 7 条定点变异（M1–M7）；含 `--state`/`--check`/`--strict`/`--json` 的输入输出面 |
| 对账夹具 | [`tests/fixtures/check_plan_golden.json`](tests/fixtures/check_plan_golden.json) ／ [`…_ledger.json`](tests/fixtures/check_plan_golden_ledger.json) | `--check` 的**固定输入**（无网可跑；由守卫 `_fixture` 派生，两处同源） |
| issue 快照导出器 | [`scripts/check_plan_snapshot.py`](scripts/check_plan_snapshot.py) | 把 issue 面导成对账可读的快照（**可选运维工具**，需 `gh` 登录；产物不提交进仓） |
| 项目管理规格 | [`docs/spec/悬赏与项目管理_v0.2.md`](docs/spec/悬赏与项目管理_v0.2.md) | 三方定义／声明态 vs 默认态／五类口径／退出码语义／机读口径／不适用条件 |
| 交付证据包 | [`docs/spec/悬赏与项目管理_v0.2_交付证据.md`](docs/spec/悬赏与项目管理_v0.2_交付证据.md) | 本条（bounty-pm）的四段式 ＋ 三字段证据块（投递草案） |
| **口径文本守卫** | [`tests/test_rule_text.py`](tests/test_rule_text.py) | 3 条断言 ＋ 8 条定点变异（R1–R8）：现行口径到位 ／ 陈旧口径不残留（扫描面含**两个生成器源**） ／ 认领通道单一——**真源改了、面向文本没跟着改**即红 |

**独立仓**：所有件自包含，不依赖任何外部仓的路径或模块——所有命令都在本仓根下跑，
只用 Python 标准库（**零第三方依赖、不触网**）。

## 二、怎么跑（全部离线）

```bash
# 1. 离线演练：一键演完整生命周期（claim→deliver→verify→settle ＋ 超时回板 ＋ 拒绝面）
python -X utf8 scripts/bounty_board.py --dry-run

# 2. 状态机守卫（逐条判据 ＋ 定点变异自证）
python -X utf8 tests/test_bounty_board.py
python -X utf8 tests/test_bounty_board.py --mutate

# 3. 生成静态站（账本 → site/ 四页；不触网）
python -X utf8 scripts/build_site.py

# 3b. 生成每日贡献表（账本 → docs/bounty/贡献表.md）
python -X utf8 scripts/daily_table.py --ledger docs/bounty/ledger.json \
    --out docs/bounty/贡献表.md

# 3c. 每日贡献表守卫（断言 ＋ 定点变异自证）
python -X utf8 tests/test_daily_table.py
python -X utf8 tests/test_daily_table.py --mutate

# 3d. 悬赏清单（生成 ＋ 自检 ＋ 守卫）
python -X utf8 scripts/bounty_list.py            # 生成 docs/bounty/悬赏清单.md
python -X utf8 scripts/bounty_list.py --check    # 产物与真源一致则 0，漂移则 1
python -X utf8 tests/test_bounty_list.py
python -X utf8 tests/test_bounty_list.py --mutate

# 3e. 插件测评站（真源 review/data/*.json → 六页产物；断言 ＋ 定点变异自证）
python -X utf8 scripts/review_build.py
python -X utf8 tests/test_review_build.py
python -X utf8 tests/test_review_build.py --mutate
python -X utf8 scripts/review_build.py --check         # 漂移闸：0=产物与真源一致 / 1=漂移
python -X utf8 scripts/evidence_check.py               # 证据链三方对账 ＋ 本机复跑逐字节复算
python -X utf8 tests/test_evidence_check.py
python -X utf8 tests/test_evidence_check.py --mutate
# 3f. 三方对账：离线对账 ＋ 漂移检测 ＋ 守卫
python -X utf8 scripts/check_plan.py --dry-run   # 对账表 ＋ 五类不一致逐行点名（退出码 0/1/2）
python -X utf8 scripts/check_plan.py --check     # 漂移检测：0=无漂移 / 1=检出漂移或输入坏（读仓内夹具）
python -X utf8 tests/test_check_plan.py

# 3g. 账本不变量自审（15 项结构不变量；非零即 rc=1 并点名）＋ 守卫（断言 ＋ 定点变异自证）
python -X utf8 scripts/check_ledger_invariants.py            # 全 0 则 0；任一项非零则 1
python -X utf8 scripts/check_ledger_invariants.py --quiet    # 只打印汇总与非零项
python -X utf8 tests/test_check_ledger_invariants.py
python -X utf8 tests/test_check_ledger_invariants.py --mutate

# 3d. 审核员机制：晋升评估 ＋ 授权面（账本 → JSON；只读、纯函数）
python -X utf8 scripts/bounty_board.py --promotion-out docs/bounty/promotion.json
python -X utf8 scripts/bounty_board.py --roles-out docs/bounty/roles.json
# 4. 网站面守卫（账本→页面映射 ＋ 定点变异自证）
python -X utf8 tests/test_build_site.py
python -X utf8 tests/test_build_site.py --mutate

# 4b. 口径文本守卫（真源 ↔ 面向文本一致性 ＋ 定点变异自证）
python -X utf8 tests/test_rule_text.py
python -X utf8 tests/test_rule_text.py --mutate

# 5. 本地预览（起个 stdlib 静态服务器，浏览器开 http://127.0.0.1:8000/site/）
python -X utf8 -m http.server 8000
```

`--state` 本地状态镜像逐步演、账本收口（`--ledger-append` ／ `--board-out`）等
详见 [`docs/bounty/README.md`](docs/bounty/README.md)。

## 三、网站面四页

| 页 | 内容 | 真源 |
|---|---|---|
| `site/index.html` | 这是什么／怎么认领／怎么交付／命令面 | 静态文案 |
| `site/board.html` | 当前**可认领**任务（按难度序） | 账本推演，或 `--tasks` 的 issue 面快照 |
| `site/honor.html` | 荣誉榜——**由账本机械生成**（分数＝delta 求和，不手写） | `docs/bounty/ledger.json` |
| `site/rules.html` | 认领-租约-验收四闸-声誉计分-争议 | 设计稿 §三/§四/§五 |

生成器命令：`python -X utf8 scripts/build_site.py`（`--print` 只打印不落盘；
`--tasks FILE` 改读 issue 面快照）。**页面确定性**：不含生成时刻，同账本 ⇒ 逐字节同一 HTML。

## 四、口径与硬约束（设计稿写死的）

- **状态机六态**：`open→claimed→delivered→verified→settled` ＋ `expired`／`disputed`；
  **`expired` 立即回 `open`**（不驻留标签）。
- **验收四闸**：① CI 全绿（机器判）② 复现读数 ③ 守卫＋定点变异 ④ **维护者人审**
  （第 ④ 闸**不许写成自动通过**）。
- **计分**：难度基准 easy 1 ／ medium 3 ／ hard 6 ／ expert 10；完成分按质量化
  `max(1, round_half_up(base×2/(round+1)))`；**超时未交付 −2×base**；轮次用尽判无效交付 −base；
  主动释放与争议提起不扣分。口径真源＝`scripts/bounty_board.py`。
  ★ **这些数值在设计稿里标着「建议值，待裁」**——代码与页面照实现，但每处都标明
  **「数值待设计者裁定」**，不写成已定（改口径只改 `scripts/bounty_board.py` 的
  `DIFFICULTY_SCORES` 与负分常量）。
- **命令只认行首最前的词**；**被拒命令记在尝试者头上**（为刷单可查）。
- **不涉资金**：仓内没有任何支付／链上／钱包代码。

## 五、本仓不做什么

- 不做任何**对外动作**：不建 issue、不打标签、不发评论、不 push、不建远端。
- workflow 真模式需显式 `--apply` 才写远端；不给就只打印计划。
