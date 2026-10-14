# `review/` —— 灵枢插件测评子站

> 把「某个插件到底行不行」做成**可复跑的读数**：每条判定都能指回一条读数，
> 每条读数都附**命令 ＋ 原始输出 ＋ 出处**，未测的项**显式写「未测 ＋ 原因」**。
> **不涉资金**、**不采集用户隐私**、**不触网**、**零第三方依赖**。

这是 `review/` 下的**限定增量**：一个真源 ＋ 一个纯 stdlib 生成器 ＋ 静态产物 ＋ 两层守卫。
它不是平台、不接数据库、没有完成码／赏金／团队——那些属于 `docs/spec/悬赏站设计_v1.0.md`
描述的**另一个产品**（《悬赏与项目管理平台》），本子站**不**实现它。

## 一、这里有什么

| 路径 | 是什么 |
|---|---|
| `review/data/plugins.json` | **唯一真源**。只改这里，改完重跑生成器；产物禁手改 |
| `review/data/rubric.json` | **评分判据真源**：五维逐维定义 ＋ 每维 5 级判据 ＋ 机械 `must` 特征；`plugins.json` 的 `rubric_version` 必须等于它的 `version`（守卫强制） |
| `review/evidence/` | **字节快照 ＋ 清单**：被引的公开文档、版本面 `package.json`、以及一次本机实跑的 stdout 记录 |
| `review/evidence/manifest.json` | 快照清单：`file`／`kind`／`source_url`／`sha256`／`bytes`／`fetched_at`／`via` |
| `review/evidence/dsh-auto-memory.budget.stdout.txt` ＋ 探针 `budget.dsh-auto-memory` | 注入段字节预算的**本机复跑**记录（跑在被测插件自己的 `renderMemoryIndexText()` 上） |
| `review/site/` | **产物**：`index.html`／`board.html`／`method.html` ＋ 每个插件一页 `detail_<slug>.html`（随仓库提交，禁手改） |
| `review/legacy/dsh-platform-v1/` | 另一份历史测评数据（PR #104），**逐字节原样保留、不参与渲染、不被守卫覆盖**；要并入现行子站需按现行五维口径**重新取数**（不折算） |
| `scripts/review_build.py` | 生成器（纯 stdlib；`--print` / `--check` / fail-closed ⇒ 退出码 2） |
| `scripts/evidence_probe.py` | **本机复跑探针**：具名纯函数，只读已提交快照，产出确定性 stdout |
| `scripts/evidence_check.py` | **证据链校验件**：快照 ←→ 清单 ←→ 真源 三方对账；`--repro` 逐字节复算本机复跑证据 |
| `tests/test_review_build.py` | 生成器守卫（逐条判据 ＋ 定点变异自证） |
| `tests/test_evidence_check.py` | 证据链守卫（逐条判据 ＋ 定点变异自证） |
| `.github/workflows/review-check.yml` | 把上面全部命令做成 CI 门禁（含「跑完不许把仓搞脏」） |

## 二、怎么跑（全部离线，零第三方依赖）

环境：**Python 3.12**，`cwd` = 仓根。

```bash
python -X utf8 scripts/review_build.py            # 生成 review/site/
python -X utf8 scripts/review_build.py --check    # 产物与真源一致则 0，漂移则 1
python -X utf8 scripts/review_build.py --rubric-report   # 评分判据对照表：逐记录逐维 分数／档位／支撑证据／must 是否满足
python -X utf8 tests/test_review_build.py         # 末行「通过 N / 失败 0」
python -X utf8 tests/test_review_build.py --mutate
python -X utf8 scripts/evidence_probe.py --list   # 列出全部探针
python -X utf8 scripts/evidence_check.py          # 三方对账 ＋ 本机复跑逐字节复算
python -X utf8 scripts/evidence_check.py --repro  # 只做复算那一段
python -X utf8 tests/test_evidence_check.py
python -X utf8 tests/test_evidence_check.py --mutate
```

退出码一律三档：**0** 一致／全绿，**1** 检出不一致（逐条点名），**2** 输入或环境错误（fail-closed）。

## 三、证据分两档（本子站的核心口径）

每条 `evidence` 都带 `kind`，页面上逐条标出：

| 档位 | 字段 | 判据 |
|---|---|---|
| **本机复跑** | `probe` | `output` 必须与 `scripts/evidence_probe.py` 对应探针的 stdout **逐字节相同**；`evidence_check.py --repro` 每次复算，差一个字节即点名判红。**每条记录至少 1 条**（生成器强制） |
| **公开文档转引** | `source`（URL ＋ 抓取日） | 原始输出取自公开文档原文，**不是**本站本机跑出来的；不许挂 `probe` |

### 本机复跑证明了什么、没证明什么

- **证明**：「我们引的字节就是这些字节」（快照 `sha256`）、「版本面与声明一致」、「这条命令现在仍跑得出这段输出」、「引用的每一句都逐字在它声明的快照里」。
- **不证明**：被测评插件的运行时行为。`dim_basis` 为空（无任何证据）的维度一律记 `null`、进 `unmeasured_dims`、**不参与**任何合计，并在「未测」节写明原因；页面上的 `1..5` 都表示**有基座**（该维挂了 ≥1 条证据），`1` 是最低档——**1–4 级的机械门槛都只是「基座非空」**，数字读数不是 1–4 级的必要条件（有没有可核数字读数由**证据档位**列另行披露）；它与「未测」不是一回事，两者都**不表示**该插件在该维度上差。

### 关于「快照 == 上游文档」

快照的 `sha256` 是**本仓这份快照**的指纹，证明「快照没被改过」；它**不**证明「这份快照与上游逐字节相同」
（上游字节未在离线条件下取指纹）。版本面一律锚在**不可变 tag**（`review/evidence/<slug>.package.json`），
因为上游 `main` 已被证实在**不升版本号**的情况下会改内容。

## 四、与仓根 `README.md` 的关系

**首次交付的补丁全为新增**：`review/` 下全部文件 ＋ 三个 `scripts/` ＋ 两个 `tests/` ＋ 一个 workflow，
那一轮**没有一行既有文件被修改**（补丁里 0 个删除／修改 hunk）。这是一条可机械复核的边界声明，
比「README 里加了注册行」更有价值。

**本次「量具修正」则相反**：它改的就是既有文件（真源、判据真源、快照清单、生成器、探针、校验件、
两个守卫与 6 页产物），改动面**以补丁为准**——「全为新增」这条边界只对首次交付那一轮成立。

两种情形下都**没有**动仓根 `README.md`：它的「这仓里有什么」表里**没有**本子站那一行。若维护者希望注册进去，
那是一条**独立的一行改动**，与本次改动面无关——请单独提，或由维护者合并时顺手加上。

## 五、边界与不做项

- **不改** `scripts/bounty_board.py`、`scripts/build_site.py`、`docs/bounty/ledger.json`、`.gitignore`。
- **不触网**：生成器、探针、校验件、守卫全部只读仓内文件、不发任何网络请求。
- **零第三方依赖**：只用 Python 标准库（有守卫断言钉住 import 白名单）。
- **不涉资金**；**不采集用户隐私**、不做用户画像。
- **运营机制**（更新节奏／提交入口／维护 SOP）不在本子站范围。
