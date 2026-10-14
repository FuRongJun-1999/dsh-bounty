# 角色扮演方向横评 · 冻结契约 v1

本文件是**唯一接口定义**：规范输入（工作负载）、语义规范（基线判据）、输出契约（适配器必须产出什么）、
统一量尺、报告结构。三家适配器、基线、评分器、守卫一律以本文件为准；任何偏离必须在报告里写明。

## 0. 目的与边界

- 目的：用**同一份规范世界书 ＋ 同一份对话历史 ＋ 同一组设置**，测出三家角色扮演方案在
  「知识注入（世界书触发）＋ 上下文预算」这一确定性面上的逐项读数。
- 只测**确定性、无 LLM** 的面。被测方案的模型调用面一律写「未测 ＋ 原因」。
- **运行期零网络、零凭据**；安装期允许使用公开镜像（本机 pip 用 Tsinghua 镜像）。
- 禁止：自己重实现被测方算法冒充其行为；用「看起来更好」这类不可判词；隐藏失败。

## 1. 规范输入（唯一工作负载定义）

由 `harness/make_fixture.py` 生成，产物固定为 `data/worldbook.json`、`data/chat.jsonl`、
`data/profiles.json`。生成器**无随机数**：同版本生成器必得同 sha256 产物（sha256 写进方法论正文）。

### 1.1 规范世界书条目（22 条 ＋ 2 条能力探针）

字段含义见 §3.1。`keys` 为触发键；`sk` = secondary_keys；`sel` = selective；
`logic` ∈ and_any | and_all | not_any；`pos` ∈ before_char | after_char | at_depth。

| uid | comment | keys | sk | sel | logic | order | pos | depth | 其他 | 测什么 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 常驻角色摘要 | —（空） | — | 否 | — | 100 | before_char | null | constant=true | 常驻条目是否无条件注入 |
| 2 | 角色基础 | 林小满 | — | 否 | — | 100 | before_char | null | — | 单键基本触发 |
| 3 | 角色别名 | 林小满, 小满 | — | 否 | — | 100 | before_char | null | — | 多键 OR |
| 4 | 雨天场景 | 林小满 | 下雨 | 是 | and_any | 100 | after_char | null | — | 二级键 and_any 命中 |
| 5 | 雨伞与咖啡馆 | 林小满 | 雨伞, 咖啡馆 | 是 | and_all | 100 | after_char | null | — | 二级键 and_all 命中 |
| 6 | 排除警察线 | 林小满 | 警察 | 是 | not_any | 100 | after_char | null | — | 反向二级键（原文无「警察」⇒ 应激活） |
| 7 | 罗马字名 | lin xiaoman | — | 否 | — | 100 | before_char | null | — | 大小写：原文为「LIN XIAOMAN」 |
| 8 | 单字「雨」 | 雨 | — | 否 | — | 100 | before_char | null | whole_words=true | 中文全词匹配（原文「下雨/雨伞」） |
| 9 | 咖啡馆·浅扫 | 咖啡馆 | — | 否 | — | 100 | at_depth | 1 | — | 深度覆盖：只扫最近 1 条 |
| 10 | 咖啡馆·深扫 | 咖啡馆 | — | 否 | — | 100 | at_depth | 6 | — | 深度覆盖：扫最近 6 条 |
| 11 | 英文词条 | starlight | — | 否 | — | 100 | before_char | null | — | 小写键 vs 原文「Starlight」 |
| 12 | 递归源 | 咖啡馆 | — | 否 | — | 100 | before_char | null | 正文含「灯塔」 | 递归扫描：正文能否触发 uid13 |
| 13 | 递归目标 | 灯塔 | — | 否 | — | 100 | before_char | null | — | 被 uid12 正文触发 |
| 14 | 递归排除 | 灯塔 | — | 否 | — | 100 | before_char | null | recursion.exclude=true | 递归激活时排除自己 |
| 15 | 道具·高权重 | 地图 | — | 否 | — | 100 | before_char | null | group=props, weight=100 | 同组择一（高权重） |
| 16 | 道具·低权重 | 地图 | — | 否 | — | 100 | before_char | null | group=props, weight=50 | 同组择一（低权重） |
| 17 | 概率条目 | 骰子 | — | 否 | — | 100 | before_char | null | probability=50 | 概率条目对确定性的影响 |
| 18 | 顺序·高 | 林小满 | — | 否 | — | 200 | before_char | null | — | 注入顺序（高 order） |
| 19 | 顺序·低 | 林小满 | — | 否 | — | 10 | before_char | null | — | 注入顺序（低 order） |
| 20 | 超长常驻 | —（空） | — | 否 | — | 100 | before_char | null | constant=true, 正文约 900 字符 | 预算溢出时被裁掉的是谁 |
| 21 | 尾声线索 | 尾声 | — | 否 | — | 100 | before_char | null | — | 只在末轮出现 |
| 22 | 停用条目 | 林小满 | — | 否 | — | 100 | before_char | null | enabled=false | 停用条目必须不激活 |
| 23 | 空键选择性 | —（空） | 下雨 | 是 | and_any | 100 | before_char | null | — | 空主键 × 选择性：边界行为 |
| 24 | 能力探针·正则键 | /地.图/ | — | 否 | — | 100 | before_char | null | capability_probe=true | 各家是否支持正则键（不支持写未测） |
| 25 | 能力探针·正则内容 | 骰子 | — | 否 | — | 100 | before_char | null | capability_probe=true, 正文为替换语法 | 各家是否做内容宏替换 |

- 正文文本由生成器给出（固定字符串），**不含**随机成分；uid20 正文由固定段落重复拼到 ≈900 字符。
- 全部条目 `probability=100`，仅 uid17 为 50。

### 1.2 对话历史（12 条消息，6 个评估轮）

`data/chat.jsonl`，每行 `{"i": <int>, "role": "system|user|assistant", "text": "<str>"}`。
评估轮 `turn k`（k=1..6）＝只喂前 `2k` 条消息（即 turn1 用 i=0..1，turn6 用 i=0..11）。

**受控事实（生成器必须逐条满足，且守卫会逐条核对）**：

| i | role | 必须包含 | 控制的读数 |
|---|---|---|---|
| 0 | system | 林小满 | 常驻/单键基线 |
| 1 | user | 下雨 | uid4 二级键、uid8 单字「雨」在「下雨」内 |
| 2 | assistant | 雨伞, 咖啡馆 | uid5 and_all、uid9/10/12 主键 |
| 3 | user | Starlight | uid11 大小写（原文大写、键小写） |
| 4 | assistant | 地图 | uid15/16 同组择一、uid24 正则键探针 |
| 5 | user | 骰子 | uid17 概率、uid25 宏探针 |
| 6 | assistant | 咖啡 | uid10 深扫（6 条）内的窗口边界 |
| 7 | user | 灯塔 | uid13/14 主键（在 turn5/6 可能落出窗） |
| 8 | assistant | 书 | 填充 |
| 9 | user | 尾声 | uid21（只在 turn5/6 出现） |
| 10 | assistant | 灯 | 填充 |
| 11 | user | LIN XIAOMAN | uid7 大小写（键小写、原文大写） |

### 1.3 设置档（`data/profiles.json`）

| 档 | scan_depth | recursive | budget_chars | case_sensitive | whole_words | 用途 |
|---|---|---|---|---|---|---|
| P0 默认 | 4 | true | 4000 | false | false | 主读数（改后/方案） |
| P1 关递归 | 4 | false | 4000 | false | false | 消融对：recursive |
| P2 浅扫 | 1 | true | 4000 | false | false | 消融对：scan_depth |
| P3 紧预算 | 4 | true | 600 | false | false | 消融对：budget（溢出策略） |
| P4 大小写＋全词 | 4 | true | 4000 | true | true | 消融对：匹配口径 |

- `recursive_max_depth` 固定为 3（若引擎支持）。
- 每档都必须产出 6 个 turn 的读数；缺档 = 该读数未测（写原因）。

## 2. 语义规范（基线判据，不是「认为」而是书面规则）

基线适配器 `adapters/baseline/run.py` 按下列顺序实现，作为「基线 vs 方案」的对照面：

1. **窗口**：turn k 的扫描窗口 = 最近 `scan_depth` 条消息（`scan_depth` 取条目 `depth` 覆盖值，否则取档位值）。
2. **主键命中**：`keys` 中任一键在窗口文本内出现即命中；`case_sensitive=false` 时按 Unicode 大小写不敏感比较；
   `whole_words=true` 时要求匹配边界（实现用 \\b 语义，对 CJK 的行为原样保留并在报告里披露）。
3. **二级键**：`selective=true` 时按 `logic` 判定（and_any / and_all / not_any），二级键在同一窗口内判。
4. **常驻**：`constant=true` 的条目不经关键词直接进入候选。
5. **停用**：`enabled=false` 的条目一律不进入候选。
6. **递归**：`recursive=true` 时，已激活条目的**正文**作为额外扫描文本，按同一键规则继续触发其它条目，
   最多 3 层；`recursion.exclude=true` 的条目在递归轮次中不参与。
7. **成组择一**：`group` 相同的候选中按 `weight` 取最大者，同权重取 uid 小者。
8. **概率**：`probability<100` 的条目按档位种子（`seed=20261014`）判；基线用 `random.Random(seed)`。
9. **排序**：先按 `order` 降序，再按 uid 升序。
10. **预算**：按排序依次累积 `content` 的字符数，超出 `budget_chars` 的条目**跳过**（不截断）并记录为 `dropped`。

## 3. 输出契约

### 3.1 规范世界书字段（`data/worldbook.json`）

```
{"schema":"roleplay-eval-worldbook/1","entries":[
  {"uid":1,"comment":"...","content":"...","keys":[],"secondary_keys":[],
   "selective":false,"selective_logic":"and_any","enabled":true,"constant":false,
   "order":100,"position":"before_char","depth":null,"probability":100,
   "case_sensitive":false,"match_whole_words":false,"group":null,"group_weight":100,
   "recursion":{"exclude":false,"prevent":false,"delay":false},
   "capability_probe":false}]}
```

### 3.2 适配器输出（`out/<name>.json`，UTF-8、键排序、无时间戳）

```
{"adapter":"sillytavern","upstream_repo":"https://github.com/SillyTavern/SillyTavern",
 "upstream_commit":"<40位sha>","adapter_version":"<引擎版本或 tag>",
 "engine_env":{"node":"v24.16.0","entry":"adapters/sillytavern/run.mjs"},
 "capabilities":{"recursive":true,"group":true,"probability":true,"regex_key":false,
                 "at_depth":true,"whole_words_cjk":"unknown"},
 "turns":[{"turn":1,"profile":"P0","history_len":2,
           "active_uids":[1,2],"inject_order":[1,2],
           "blocks":[{"uid":1,"position":"before_char","depth":null,"chars":56,"bytes":168,"sha256":"..."}],
           "totals":{"active":2,"chars":56,"bytes":168,"dropped_uids":[]},
           "engine_notes":[]}],
 "unsupported":[{"field":"regex_key","reason":"..."}],
 "errors":[]}
```

- `active_uids`：本 turn 被激活并注入的条目 uid 集合（升序）。
- `inject_order`：**引擎实际注入顺序**（这是读数，不是规范值）。
- `blocks`：每个注入块的 position/depth/字符数/字节数/正文 sha256（正文只进 raw，不要求进 out）。
- `dropped_uids`：被预算裁掉的 uid；引擎无预算概念就写 `[]` 并在 `unsupported` 说明。
- `unsupported`：字段级能力缺口，逐条给原因。**写「未测」不算缺证据，不许留空**。
- `errors`：非空即视为该档失败，必须原样贴进报告。

### 3.3 适配器 CLI 契约

```
<引擎运行时> adapters/<name>/run.<ext> --data data --profile P0 --out out/<name>_P0.json
```

- 必须**只读** `data/`，只写 `out/`；不得改 `data/`。
- 不得访问网络；不得读工作目录以外的用户数据。
- 退出码 0 表示产出完整；非 0 必须同时写 `errors`。

## 4. 统一量尺

| 量尺 | 定义 | 备注 |
|---|---|---|
| chars | Unicode 码点数（Python `len(s)`） | 跨引擎可比 |
| bytes | UTF-8 字节数（`len(s.encode('utf-8'))`） | 跨引擎可比 |
| tokens(引擎) | 各家自带 token 估算 | **方案内口径，不可跨引擎比较**，只作附注 |
| 激活集 | `active_uids` 集合 | 主读数 |
| 差异集 | 两家（或方案 vs 基线）在同一 (profile, turn) 上的对称差 | 逐条可指 |
| 顺序差异 | `inject_order` 的逆序对数 | 仅在同激活集上算 |

## 5. 报告结构（强制，守卫逐条核对）

`docs/reviews/<方案名>_v0.1.md` 必须逐字含下列二级标题，且顺序一致：

```
## 0. 结论摘要          ← 每条结论必须带 M1–M8 编号引用
## 1. 被测对象与版本    ← 仓库 URL ＋ 精确 commit sha
## 2. 复现步骤          ← 含可原样粘贴的命令
## 3. 基线 vs 方案对照读数
## 4. 读数明细
## 5. 不适用条件         ← ≥40 字符
## 6. 未测项与原因       ← 含「未测」二字，≥40 字符
```

`docs/reviews/测评方法论_角色扮演_v0.1.md` 用 1–9 节，含「读数项」「公平性规则」「复现步骤（第三方原样可跑）」
「不适用条件」「未测项与原因」五个具名标题，且**正文**写出 `data/worldbook.json` 的 sha256 与
`data/chat.jsonl` 的 sha256。

读数项编号（全件统一）：

| 编号 | 读数 |
|---|---|
| M1 | 激活集：方案 vs 基线（P0，逐 turn） |
| M2 | 注入顺序：方案 vs 基线（同激活集上） |
| M3 | 预算溢出：P0 vs P3 的 dropped_uids 差异 |
| M4 | 递归消融：P0 vs P1 的激活集 Δ |
| M5 | 深度消融：P0 vs P2 的激活集 Δ |
| M6 | 确定性：同一输入重复 5 次，输出 sha256 是否逐字节一致 |
| M7 | 匹配口径消融：P0 vs P4 的激活集 Δ（大小写＋全词） |
| M8 | 代价：初始化耗时、单档端到端耗时、依赖安装体积、零凭据可运行性 |

## 6. 禁令

- 不得用自写循环冒充引擎能力：能力不支持的字段写 `unsupported` 并说明依据（源码行号或官方文档 URL）。
- 不得把 `engine_notes` 当作读数；读数只能来自 `out/` 与 `raw/`。
- 不得在报告里出现「未测」之外的空缺；不得用「应该没问题」代替。
- 不得采集任何用户隐私数据；夹具全部为自建合成内容。

## 7. 原始日志布局与读数行语法

### 7.1 文件布局（全部落在 `bench/roleplay_eval/`）

| 路径 | 内容 |
|---|---|
| `raw/<name>_<profile>.txt` | 该档运行的**逐字 stdout**（含下面定义的全部读数行） |
| `raw/<name>_<profile>.json` | 适配器输出副本（与 `out/<name>_<profile>.json` 逐字节相同） |
| `raw/<name>_baseline_diff.txt` | 方案 vs 基线的 DIFF 读数行（逐 turn） |
| `raw/<name>_repeat.txt` | 确定性重复运行的 stdout（5 次，含 DETERMINISM 行） |
| `raw/<name>_summary.json` | `{"adapter":..,"profiles":{"P0":{...}},"determinism":{...}}` 供守卫读 |
| `raw/baseline_<profile>.txt` | 基线同口径 |

### 7.2 读数行语法（固定前缀 ＋ 空格分隔键值；`sha256` 一律 64 位小写十六进制）

```
READOUT <adapter> <profile> turn=<k> active=<n> order=<uid,uid> chars=<n> bytes=<n> dropped=<uid,uid>
DIFF <a> <b> <profile> turn=<k> only_a=<uid,uid> only_b=<uid,uid> same=<n>
KPI <metric> value=<num> ci=[<lo>,<hi>] n=<int>
SHA <hex64> file=<相对路径>
DETERMINISM <adapter> repeats=<n> identical=<true|false> sha=<hex64>
TIMING <adapter> profile=<P> min_ms=<num> p50_ms=<num> p95_ms=<num>
CAPS <adapter> {"recursive":true,"group":true,"probability":true,"regex_key":false,"at_depth":true}
UNSUPPORTED <adapter> field=<name> reason=<无空格短标记>
ERROR <adapter> profile=<P> kind=<name>
```

- 空集合一律写 `-`（例如 `only_a=-`），不得留空。
- 报告里围栏代码块中出现的**任何**以这些前缀开头的行，必须能在 `raw/` 某个文件里**逐字**找到（守卫判据 R5）。
- `chars`/`bytes` 按 §4 口径；`tokens(引擎)` 只允许出现在报告正文，不进读数行。

### 7.3 报告引用规则

- 报告引用 `raw/<文件>` 时**必须带扩展名**，且文件必须真实存在（守卫判据 R4）。
- 报告的每个结论条目必须带至少一个 M 编号；结论摘要至少引用 3 个不同 M 编号（守卫判据 R12）。
