# RisuAI 适配器（角色扮演横评 · 第三份交付）

被测对象：`https://github.com/kwaroran/Risuai`，commit `454e5e207747399f43a4788f5f08ecd5aa291550`，GPL-3.0。

本目录把 CONTRACT §1 的规范世界书、对话历史、档位翻译成 RisuAI 的 `loreBook` 与 `loreSettings`，
再调用 RisuAI 本体代码跑出 §3.2 读数。触发、递归、预算、排序、token 估算全部由上游代码执行；
本目录只做字段翻译与读数格式化，不含任何重写的等价算法。

## 1. 目录与产物

| 路径 | 说明 |
|---|---|
| `fetch_upstream.sh` | 用 codeload 取上游源码到 `upstream/`，并核对 `package.json` 的 git blob sha1 |
| `setup.sh` | `npx --yes pnpm@10.34.1 install --frozen-lockfile` |
| `run.mjs` | 适配器入口（CONTRACT §3.3）：翻译夹具 → 注入用例 → 跑 vitest → 解析读数 → 写 `--out` |
| `inject/rp67_adapter.test.ts` | 注入用例，运行时复制到 `upstream/src/ts/poc/rp67_adapter.test.ts` |
| `upstream/` | 上游源码与依赖，不进版本库；`fetch_upstream.sh` + `setup.sh` 可重建 |
| `.det/` | 复跑用的临时产物（5 次确定性运行的 out、零网络运行的 out）。可整目录删除，删后按 §2 重跑即重建 |
| `.gitignore` | 排除 `upstream/` 与 `.det/`，两者都不进版本库 |

`upstream/src/ts/poc/rp67_fixture.json` 由 `run.mjs` 每次运行重写，内容只来自 `data/`，不带时间戳。

## 2. 复现命令

在 `bench/roleplay_eval/` 下执行。

```bash
bash adapters/risuai/fetch_upstream.sh
bash adapters/risuai/setup.sh
node adapters/risuai/run.mjs --data data --profile P0 --out out/risuai_P0.json
python -X utf8 harness/validate.py out/risuai_P0.json
python -X utf8 harness/runner.py --adapter risuai --profiles P0,P1,P2,P3,P4
python -X utf8 harness/score.py --name risuai
```

零网络复跑（Node 权限模型开启，不给 `--allow-net`）：

```bash
node adapters/risuai/run.mjs --data data --profile P0 --out out/risuai_P0_nonet.json --engine permissioned
```

`--engine permissioned` 把同一批用例换成
`node --permission --allow-fs-read=* --allow-fs-write=* --allow-worker --allow-addons --allow-child-process node_modules/vitest/vitest.mjs run src/ts/poc/rp67_adapter.test.ts`。
`--allow-addons`、`--allow-child-process` 是加载已装原生模块与起 vitest 子进程所必需；`--allow-net` 未给，网络系统调用被拒。

## 3. 被测代码边界

被调用的上游真代码：

| 文件 | 用途 |
|---|---|
| `src/ts/process/lorebook.svelte.ts` | `loadLoreBookV3Prompt`：触发、二级键、递归、预算、排序 |
| `src/ts/tokenizer.ts` | `tokenize`：token 估算，被 `loadLoreBookV3Prompt:581` 调用 |
| `src/ts/parser/parser.svelte.ts` | `risuChatParser`：CBS 求值，被 `:581` 调用 |
| `src/ts/process/prompt.ts` | `detectPromptJSONType` / `stChatConvert` |
| `src/ts/parser/chatML.ts` | `parseChatML` |

唯一被替换的模块是全局状态容器 `src/ts/stores.svelte`（提供 `DBState` / `selIdState` / `selectedCharID`）。
仓库自带测试 `src/ts/parser/tests/cbs/strings.test.ts:23-61` 用同一做法，原因是模块级 `$effect`
与循环导入在 vitest 的 SSR 转换下报 `Cannot read properties of undefined (reading 'selId')`
（`src/ts/parser/parser.svelte.ts:463-465`）。该替换不影响 `loadLoreBookV3Prompt` 的任何分支。

tokenizer 固定 `db.aiModel = 'openrouter'`、`db.customTokenizer = ''`，走 `tokenizer.ts:105` →
`:131-133` 的本地 tiktoken 分支（`@dqbd/tiktoken`，词表 `o200k_base`）。
gemma / gemini 两条分支会 `fetch`（`tokenizer.ts:261`、`:297`、`:336`、`:352`），本适配器不使用。

## 4. 字段映射表：规范世界书字段 → RisuAI loreBook 原生字段

| 规范字段 | RisuAI 原生字段 / 机制 | 映射写法 | 依据（上游行号） |
|---|---|---|---|
| `uid` | `loreBook.id` | `rp67-<uid>`，只作稳定标识 | `storage/database.svelte.ts:1357` |
| `comment` | `loreBook.comment` | 原样写入；同时是 `actives[].source`，用它反查 uid | `lorebook.svelte.ts:583` |
| `content` | `loreBook.content` | 装饰器行前置，正文原样接在后面 | — |
| `keys` | `loreBook.key` | 逗号连接；上游按 `key.split(',')` 展开为任一命中 | `lorebook.svelte.ts:528` |
| `secondary_keys` + `selective_logic=and_any` | `loreBook.secondkey` + `loreBook.selective` | 逗号连接，追加一条必须命中的正向查询 | `:532-537` |
| `secondary_keys` + `selective_logic=and_all` | 每个二级键一行 `@@additional_keys <键>` | 逐行各产生一条必须命中的正向查询 | `:444-450` |
| `secondary_keys` + `selective_logic=not_any` | 一行 `@@exclude_keys <键 键 ...>` | 负向查询命中即整条否决 | `:451-457` |
| `selective=false` | `secondkey=''`、`selective=false` | 不追加二级查询 | `:532` |
| `enabled` | `@@dont_activate` | 强制 deactivate，条目永不被注入 | `:482-485`、`:566-568` |
| `constant` | `loreBook.alwaysActive` | 跳过搜索直接入候选 | `:523-525` |
| `order` | `loreBook.insertorder` | 直接写入，并成为 `actives[].order` 与初始 `priority` | `:278-279` |
| `position=before_char` | 不加位置装饰器 | 上游默认 `pos=''` | `:269` |
| `position=after_char` | `@@position after_desc` | `pos='after_desc'` | `:389-395` |
| `position=at_depth` | `@@depth <n>` | `pos='depth'`、`depth=n` | `:352-361` |
| `depth`（窗口覆盖） | `@@scan_depth <n>` | 覆盖该条目的搜索窗口 | `:375-378` |
| `match_whole_words` | 条目级 `@@match_full_word`；档位级 `loreSettings.fullWordMatching` | 两者取或 | `:466-469`、`:86`、`:192-209` |
| `recursion.exclude` | `@@no_recursive_search` | 递归语料不进本条目的搜索窗口 | `:512-515`、`:137` |
| 正则键（`/地.图/`，uid24） | `loreBook.useRegex=true` + `key` 写 `/pattern/flags` | 键必须整体是正则字面量；不支持混合写法（有一条不是正则字面量就整条判否） | `:145-177`、`:543` |
| `probability` | 有 `@@probability` 装饰器，但实现用 `Math.random()` | 不使用；见 §5 | `:493-498` |
| `case_sensitive` | `loreBook.extentions.risu_case_sensitive` 只在卡片导入导出里读写 | 不生效；见 §5 | `database.svelte.ts:1347-1349`、`characterCards.ts:1152` |
| `group` / `group_weight` | 无分组字段 | 不使用；见 §5 | `database.svelte.ts:1338-1359` |
| `recursion.prevent` / `recursion.delay` | 无对应字段或装饰器 | 不使用；见 §5 | — |
| `capability_probe` | 夹具侧标记，非引擎字段 | 忽略 | — |

定位扫描窗口的 `scan_depth` 走 `loreBook.key` 的搜索深度（`:108` 的 `messages.slice(len - searchDepth, len)`），
不是注入深度；注入深度只由 `@@depth` 决定。夹具里 uid9 / uid10 同时带 `position=at_depth` 与 `depth`，
因此同时拿到 `@@depth n` 与 `@@scan_depth n` 两个装饰器。

## 5. 档位字段映射表：规范 profile → RisuAI 设置

| 档位字段 | RisuAI 原生字段 | 映射写法 | 依据 |
|---|---|---|---|
| `scan_depth` | `char.loreSettings.scanDepth`（缺省回落 `db.loreBookDepth`） | 直接写入 | `lorebook.svelte.ts:84` |
| `recursive` | `char.loreSettings.recursiveScanning` | 直接写入 | `:88` |
| `whole_words` | `char.loreSettings.fullWordMatching` | 直接写入 | `:86` |
| `budget_chars` | `char.loreSettings.tokenBudget`（缺省回落 `db.loreBookToken`） | 同数值直传，**上游计 token 不计字符** | `:85`、`:617-625` |
| `case_sensitive` | 无生效字段 | 不写入；见下 | — |
| `recursive_max_depth` | 无对应：上游 `while(matching)` 跑到不动点 | 不写入；见下 | `:259-611` |
| `seed` | 只服务概率判定 | 概率已 unsupported，无效果 | `:493-498` |
| 对话历史 | `char.chats[page].message` | turn k 只放前 `2k` 条 | `:83`、`:87` |
| 消息 role | `Message.role`（`'user'`/`'char'`） | 夹具 `user` → `'user'`；夹具 `system`/`assistant` → `'char'` | `:122-135` |

消息 role 只影响上游 matchLog 的标签文字；命中判定只读正文（`:191-228` 用 `m.data`）。

## 6. unsupported 字段

`out/risuai_*.json` 的 `unsupported` 数组与本表一一对应（`reason` 为无空格短标记）。
判据是「该字段的语义不能靠上游已有字段或装饰器表达」，或「上游有该字段但被触发路径忽略」。

| 字段 | reason | 判据 |
|---|---|---|
| `probability` | `upstream-decorator-uses-Math.random-lorebook.svelte.ts:494` | 用 `@@probability` 会引入不可复现的随机数。契约 uid17 的 `probability=50` 因此不生效：只要主键命中就注入 |
| `case_sensitive` | `upstream-folds-case-unconditionally-lorebook.svelte.ts:182` | 类型里有 `extentions.risu_case_sensitive`，但 `loadLoreBookV3Prompt` 不读它，`:182-183`/`:195`/`:213` 一律 `toLocaleLowerCase`。P4 档的大小写部分在 RisuAI 侧无效果 |
| `group` | `no-group-field-in-loreBook-database.svelte.ts:1338` | `loreBook` 无分组字段。uid15/uid16 同组择一在 RisuAI 侧不发生 |
| `group_weight` | `no-group-field-in-loreBook-database.svelte.ts:1338` | 同上；`weight` 无处安放 |
| `recursion.prevent` | `no-upstream-field` | 无对应字段或装饰器。夹具中该值恒为 `false`，不影响读数 |
| `recursion.delay` | `no-upstream-field` | 同上 |
| `capability_probe` | `fixture-side-marker-no-upstream-field` | 夹具侧标记，非引擎字段 |
| `budget_chars` | `upstream-budget-counts-tokens-not-chars` | 上游预算单位是 token（`:581` 用 `tokenize` 计数，`:619-625` 比较 `tokenBudget`）。字符预算无法在不改上游代码的前提下表达；映射取同数值直传，单位差异在报告里披露 |
| `recursive_max_depth` | `upstream-loops-to-fixpoint-without-depth-cap` | 上游递归是 `while(matching)` 不动点循环，没有层数上限；固定的 3 层无法表达 |
| `seed` | `no-effect-because-probability-unsupported` | 概率判定是 `Math.random`，不接受种子，档位 `seed` 无处使用 |

## 7. 读数口径

- `inject_order` = `loadLoreBookV3Prompt` 返回数组的顺序。上游先按 `priority` 降序、按 `tokenBudget` 裁剪，
  再按 `order` 降序，最后 `reverse()`（`:613-629`、`:667`），所以实际注入顺序是 **order 升序**；
  同 `order` 时因 `Array.prototype.sort` 稳定而保持「插入序的倒序」。
- `chars` / `bytes` / `sha256` 取自 `actives[].prompt`，即装饰器剥离后的注入正文。
  P0–P4 五档全部与 `data/worldbook.json` 的 `content` 逐字相同，`validate.py --strict-content` 全绿。
- `dropped_uids`：上游不回报被预算裁掉的条目，本适配器用同一 turn 的两次真实引擎运行的差集得出——
  `tokenBudget=档位值` 与 `tokenBudget=1000000000` 两次调用，后者激活集减去前者激活集即被裁条目。
  两次调用走同一个 `loadLoreBookV3Prompt`，没有本适配器自写的裁剪逻辑。
- 内容宏：uid25 正文里的 `{{roll:d6}}` 会被 `risuChatParser` 求值（用于 token 估算，`:581`），
  但 `actives[].prompt` 保留原文。`{{roll}}` 内部用随机数，故 `EXTRA` 行只记录「是否发生替换」的布尔值，
  不记录替换结果。
- 正则键能力：夹具 uid24 的键是 `/地.图/`，正则语义要求 `地` 与 `图` 之间再有一个字符，而夹具窗口里的正文是「地图」两字，因此该条目在 P0–P4 五档里都不激活（基线的字面比较同样不命中）。能力本身由 `EXTRA` 行的正对照证明：
  `regex_key_probe_hits=[三字窗口命中数,两字窗口命中数]`，实测 `[1,0]`，即同一 `useRegex` 条目在「这里标着地标图。」下激活、在「我把地图折好塞进背包。」下不激活。
- `EXTRA …` 行是本适配器自加的附注，不是 §7.2 读数行；`CAPS`、`READOUT`、`UNSUPPORTED`、`ERROR` 才是契约行。

## 8. 与基线的口径差异（读数解读时先看这里）

| 差异 | 基线 | RisuAI | 影响的读数 |
|---|---|---|---|
| 概率 | `random.Random(20261014)` 可复现 | `Math.random`，不可复现，故不使用 | M1：uid17 在 RisuAI 侧恒注入，基线按种子判决 |
| 成组择一 | 实现 | 无字段 | M1：uid15 与 uid16 在 RisuAI 侧同时注入 |
| 大小写 | 档位/条目可取或 | 一律折叠大小写 | M7：P4 只体现全词部分 |
| 预算单位 | 字符 | token | M3：两档裁剪阈值不可直接换算 |
| 递归层数 | 固定 3 层 | 跑到不动点 | M4 |
| 全词匹配 | `\b` 语义，对 CJK 无边界则退回子串包含 | 按空格切词，CJK 整句成一个词 | M7：P4 档 RisuAI 侧中文条目几乎全不命中 |
