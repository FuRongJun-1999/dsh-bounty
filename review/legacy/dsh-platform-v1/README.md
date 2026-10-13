# review/legacy/dsh-platform-v1/ —— 保留的历史测评数据（**不参与渲染**）

## 这是什么

这是 **PR #104**（作者 @acrot0）交付的插件测评数据，**逐字节原样保留**：

| 文件 | 来源 | 字节 | sha256（前 16） |
|---|---|---|---|
| `plugins.json` | `PR #104` 的 `review/data/plugins.json` | 18397 | `6638e4887ab2a0cf` |
| `method.json` | `PR #104` 的 `review/data/method.json` | 5299 | `424d165c8cb0590f` |

## 为什么放在这里，而不是 `review/data/`

PR #104 与 PR #161 是**两次独立交付**，都满足悬赏 `eval-site` 的验收标准，
但**真源 schema 不兼容**，无法合成一份：

| | #104 | #161（现行引擎） |
|---|---|---|
| 顶层 | `{"schema","plugins":[…]}` | `{"_schema","records":[…]}` |
| 维度 | 定性发现 `{name, finding, basis}`（4 条／插件） | **五维读数 1–5 整数**（固定五维名） |
| 证据 | `{command, output, source, captured_at}` | `{kind, cmd, output, source, doc, quotes, probe?}` |
| 被测插件 | `dsh-better-sidebar` / `dsh-cost-meter` / `dsh-office-tools` | `dsh-memory` / `dsh-mnemon` / `dsh-auto-memory` |

**两组的被测插件完全不相交**（平台／运维类 vs 记忆类）⇒ 不是「谁取代谁」，而是**覆盖面互补**。
但 #161 的生成器把 `dimensions` 强制为五维 1–5 整数，而 #104 的维度是定性发现——
**把定性发现折成 1–5 分数属于新造读数，不是合并**，故本仓**不做**这种折算。

## 现状与后续

- 现行引擎（#161）只读 `review/data/plugins.json`，**不读本目录**；本目录**不参与渲染**，也不被守卫覆盖。
- 保留的理由：其中的**本机实测读数**（如 `sidebar_open` 324 tok/轮、npm 关键词扫得 87 个包、
  bundle 面两向夹具 8/8）是真实采集的产物，删掉即丢失。
- 后续若要把这 3 个插件并入现行子站，需要的是**按现行五维口径重新取数**（而不是折算），
  那是一次独立的测评工作，不是本目录的搬运。

> 保留方式：`git show <PR #104 合并提交>:<原路径>` 逐字节写出，未做任何编辑。
