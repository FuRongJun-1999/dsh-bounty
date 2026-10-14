# SillyTavern 适配器（角色扮演横评 · 世界书触发 ＋ 上下文预算）

被测对象：`SillyTavern/SillyTavern` commit `06bde939fb1e9c4c8d8641d810f0a916b5bce127`（release 分支，2026-09-14），
引擎版本 `package.json` 的 `1.19.0`。适配器脚本版本 `st-roleplay-eval-adapter/0.1`。

读数来自被测方自己的前端模块 `public/scripts/world-info.js`：适配器在 chromium 页面里
`await import('./scripts/world-info.js')`，用 `setWorldInfoSettings` ＋ `checkWorldInfo(chat, maxContext, true)` 取数。
适配器不实现任何触发逻辑、不重写任何排序或预算规则。

## 一、文件

| 文件 | 作用 |
| --- | --- |
| `fetch_upstream.sh` | 按锁定 sha 从 codeload 取源码到 `upstream/`，并校验 `package.json` 的 `version` |
| `setup.sh` | `npm ci` ＋ `cd tests && npm install`；浏览器默认跑 `npx playwright install chromium` |
| `run.mjs` | 适配器主体：起服务、写世界书、在页面里取读数、打印读数行、写契约 JSON |
| `verify_determinism.mjs` | 控种路径：同输入连跑 N 次（每次一个独立 node 进程），比对 stdout 与 out JSON 的 sha256 |
| `verify_determinism_native.mjs` | 原生路径：每次带 `--no-seed` 连跑 N 次，量上游随机源造成的差异；out JSON 写临时目录，不覆盖 `out/sillytavern_P*.json` |
| `.gitignore` | `upstream/` 不进版本库 |
| `upstream/` | 只读源码快照，由 `fetch_upstream.sh` 重建；本适配器只写它自己的用户目录 `data/default-user/worlds/` |

## 二、依赖、体积与耗时（本机实测）

环境：Windows 11 ＋ MSYS2/Git-Bash，node v24.16.0、npm 11.13.0。

| 项 | 实测值 |
| --- | --- |
| codeload 压缩包 | 38,087,675 字节，sha256 `d3c5b32e7a1b649366d7d35eaaf877b06376864aacd8713ee8e670ff8ee4099c` |
| 快照文件数 / 版本 | 1010 文件；`package.json` version `1.19.0` |
| `npm ci` | 9 s，829 个包（npm 缓存已热） |
| `upstream/node_modules` | 337,045,122 字节 / 24,366 文件 |
| `cd tests && npm install` | 依赖已就位时 1 s（up to date）；`upstream/tests/node_modules` 45,665,607 字节 / 5,923 文件 |
| `upstream/` 合计 | 474,833,878 字节 / 31,510 文件（含两个 node_modules 与运行时 `data/`） |
| 冷起服务（`node server.js --port 8123` → HTTP 200） | 3,336 ms |
| 单档端到端（冷起，P0，含服务启动） | 8,721 ms（`raw/sillytavern_timing.txt`） |
| 单档端到端（服务已监听，runner 计时口径，P0..P4） | min 3,484 ms，p50 3,707 ms，p95 4,200 ms（`raw/sillytavern_runner.txt`） |

### 浏览器（如实披露）

`setup.sh` 默认执行 `npx playwright install chromium`。**本机实测该命令在解压阶段挂死（2/2 复现，证据 `spike/st-roleplay/SPIKE.md` §4.3）**。
绕过办法：`CHROME_PATH` 指向已装 chrome，`setup.sh` 据此跳过下载，`run.mjs` 把它作为 Playwright 的 `executablePath`：

```
CHROME_PATH=C:/Users/Zs/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe
```

本适配器的读数不依赖 `npx playwright install chromium` 的产物；该命令的解压耗时与完整体积本适配器未测（原因见交付报告第 6 节）。

## 三、run.mjs 调用的 ST 代码

| 步骤 | 入口 | 位置 |
| --- | --- | --- |
| 世界书文件读取 | `loadWorldInfo` → `POST /api/worldinfo/get` → `readWorldInfoFile` | `public/scripts/world-info.js:2036`、`src/endpoints/worldinfo.js:71`、`:17` |
| 设置注入 | `setWorldInfoSettings(settings, data)` | `public/scripts/world-info.js:917`（`world_info` 数组分支 `:960-963`） |
| 条目集合 | `getGlobalLore` → `getSortedEntries` | `:4527`、`:4590`（排序 `sortFn` `:88`） |
| 扫描与激活 | `checkWorldInfo(chat, maxContext, isDryRun)` | `:4709` |
| 扫描窗口 | `WorldInfoBuffer.get`：`entry.scanDepth ?? world_info_depth` | `:280`、`:402` |
| 键匹配（含正则键） | `WorldInfoBuffer.matchKeys`；正则分支 `parseRegexFromString` | `:337-366`、`:2901` |
| 二级键 | AND_ANY／NOT_ALL／NOT_ANY／AND_ALL | `:4943-4978`；枚举 `:33-38` |
| 常量条目 | `entry.constant` | `:4893` |
| 停用条目 | `entry.disable` | `:4801` |
| 递归 | `world_info_recursive` ＋ `excludeRecursion` ＋ 递归缓冲 | `:4870`、`:5097-5100`、`:5138-5144` |
| 成组择一 | `filterByInclusionGroups`（加权随机 `Math.random()`） | `:5452-5473` |
| 概率 | `verifyProbability`（`Math.random() * 100`） | `:5041` |
| 预算 | `Math.round(world_info_budget * maxContext / 100)`；溢出 `continue` | `:4736-4741`、`:5061-5073` |
| 注入组装 | 按 `sortFn` 遍历后 `unshift` 进 before／after／at_depth 桶 | `:5203-5266` |
| 正文宏替换 | `substituteParams(entry.content)` | `:5058` |
| 页面取数形状 | `script.js` 的 `coreChat.map(...).reverse()` | `public/script.js:4624` |

## 四、字段映射表（规范世界书 25 条 → ST 世界书）

适配器把 `data/worldbook.json` 的 25 条逐条写成 ST 世界书 `{"entries":{"<uid>":{...}}}`，
写入 `upstream/data/default-user/worlds/roleplay_eval.json`（P0 映射另存 `roleplay_eval_p0.json`，供锚点搜索用）。

| 规范字段 | ST 世界书字段 | 口径 |
| --- | --- | --- |
| `uid` | `uid`（同时用作 `entries` 的键） | 直通；ST 的 `entry.uid` 就是读数里的 uid（`:4535`） |
| `comment` | `comment` | 直通 |
| `content` | `content` | 直通；注入时经 `substituteParams`（`:5058`）与 `getRegexedString`（`:5205`） |
| `keys` | `key`（数组） | 直通；写成 `/…/` 时 ST 按正则执行（`:339-342`） |
| `secondary_keys` | `keysecondary` | 直通 |
| `selective` | `selective` | 直通；次选键为空时不经次选判定（`:4924-4935`） |
| `selective_logic` | `selectiveLogic` | `and_any`→0、`not_all`→1、`not_any`→2、`and_all`→3（`:33-38`） |
| `enabled` | `disable`（取反） | 直通 |
| `constant` | `constant` | 直通 |
| `order` | `order` | 字段值直通；排序方向由引擎决定（`:88` `b.order - a.order`） |
| `position` | `position` | `before_char`→0、`after_char`→1、`at_depth`→4（`:855-864`） |
| `depth` | `scanDepth` ＋ `depth` | 同名字不同义：`scanDepth` 是扫描窗口（契约 §2 规则 1 的语义），`depth` 是插入深度（ST 语义）。夹具值同时写入两处；`depth` 为 null 的条目插入深度取 ST 默认 4 |
| `probability` | `probability` ＋ `useProbability=true` | 直通；`<100` 时过随机判定（`:5041`） |
| `case_sensitive` | `caseSensitive` | 条目级 OR 档位值（`entry.caseSensitive ?? world_info_case_sensitive`，`:269`） |
| `match_whole_words` | `matchWholeWords` | 条目级 OR 档位值（`:347`） |
| `group` | `group`（空写 `''`） | 直通 |
| `group_weight` | `groupWeight` | 值直通，但仲裁规则不同（ST 加权随机，契约取最大权重）⇒ 见第五节 |
| `recursion.exclude` | `excludeRecursion` | 直通（`:4870`） |
| `recursion.prevent` | `preventRecursion` | 直通（`:5080`） |
| `recursion.delay` | `delayUntilRecursion` | 值直通，但契约未定义 delay 语义 ⇒ 见第五节 |
| `capability_probe` | 不写入 | 夹具标记，ST 无对应字段 |

**uid25 不参与内容溯源**：uid25 的 `content` 是 `内容宏探针：{{roll:d6}} 与 {{user}} 原样保留，不做替换。`（39 字符 / 73 字节）。
ST 在注入前对它执行 `substituteParams`（`world-info.js:5058`），`{{roll:d6}}` 被 `macros.js:566` 的 `droll.roll()` 换成 1–6 的整数、`{{user}}` 换成 `User`，
注入文本因此变成 25 字符 / 59 字节，与夹具原文不等。其余 24 条的注入正文逐字节等于夹具原文（`harness/independent_recompute.py` 的 `PROVENANCE` 行）。
本适配器保留该条的注入读数（它就是「各家是否做内容宏替换」的探针答案），但**该条不参与内容溯源比对**；三种观测值见交付报告第 4.6 节。

适配器另外写入的固定值（夹具无对应字段）：`vectorized=false`、`sticky=null`、`cooldown=null`、
`delay=null`、`role=0`、`triggers=[]`、`ignoreBudget=false`、`addMemo=true`、`displayIndex=<条目序号>`、
`outletName=''`、`groupOverride=false`、`useGroupScoring=null`、`automationId=''`。

## 五、映射不上 ⇒ unsupported（5 条）

| 字段 | reason（读数行用） | 依据 |
| --- | --- | --- |
| `group_weight` | `st-group-winner-is-weighted-random-not-max-weight` | 契约 §2 规则 7 是「同组取 weight 最大、同权取 uid 小」；ST 的组内仲裁是 `Math.random()` 加权抽签（`world-info.js:5452-5473`），无「取最大」这一语义 |
| `recursion.delay` | `contract-defines-no-delay-rule-and-st-semantics-differs` | 契约 §2 的十条规则没有 delay；ST 的 `delayUntilRecursion` 是「推迟到递归轮次」（`:4860-4868`）。夹具 25 条全为 `delay=false`，本档读数不受影响 |
| `capability_probe` | `fixture-marker-not-an-engine-field` | 夹具标记；uid24／uid25 分别按 `key`／`content` 常规处理 |
| `budget_chars` | `st-budget-is-token-share-of-max-context-not-chars` | ST 预算是 token 且是 `maxContext` 的百分比（`:4736`），契约预算是字符。口径换算见第六节 |
| `whole_words_cjk` | `st-whole-word-boundary-treats-cjk-as-non-word-char` | ST 的单键全词用 `(?:^|\W)(key)(?:$|\W)`（`:356`）；JS 正则里 CJK 属 `\W`，故「雨」在「下雨」内仍命中。基线的 `\b` 语义不命中，两家在 uid8 上分叉 |

## 六、档位映射与预算口径（必须披露）

| 档位字段 | 适配器做法 | ST 依据 |
| --- | --- | --- |
| `scan_depth` | `world_info_depth` | `:402` `world_info_depth`；条目级 `scanDepth` 覆盖它 |
| `recursive` | `world_info_recursive` | `:5097` |
| `recursive_max_depth`＝3 | `world_info_max_recursion_steps = 4`（1 次初扫 ＋ 3 层递归） | `:4768` 用 `count` 计数整个 while 循环 |
| `case_sensitive` / `whole_words` | 全局 `world_info_case_sensitive`／`world_info_match_whole_words` ＋ 条目级 OR | `:269`、`:347` |
| `seed` | 每次 `checkWorldInfo` 前把页面上下文里的 `Math.random` 换成 `lcg32(seed + turn*1000003)`，调用后立刻还原 | 见下方「控种口径」 |
| `budget_chars` | 见下 | ST 无字符预算 |

**控种口径（必须披露）**

- **替换了哪个随机源**：只替换页面上下文里的全局 `Math.random`。上游三处随机都经它取数：概率判定 `world-info.js:5041`（`Math.random() * 100`）、
  成组择一 `world-info.js:5453`（`Math.random() * totalWeight`）、内容宏 `{{roll:}}` `macros.js:566` → `node_modules/droll/droll.js:96`（`1 + Math.floor(Math.random() * numSides)`）。
- **怎么替换**：`run.mjs` 在页面里用 `makeRng(seed)` 生成 32 位 LCG（`s = s*1664525 + 1013904223`，取高 32 位后除以 2^32），
  每个 turn 装一次 `seed + turn*1000003`；`await checkWorldInfo(...)` 返回后在 `finally` 里还原为原函数。种子取 `data/profiles.json` 的 `seed`（20261014），与基线 `random.Random(20261014)` 同种子口径。
- **为什么不算改引擎行为**：`upstream/` 源码零改动（快照由 `fetch_upstream.sh` 按锁定 sha 重建，只写它的用户数据目录 `data/default-user/worlds/`）；
  替换只发生在被测函数的调用边界外，不改变任何触发、排序、预算、递归逻辑，只给引擎一个可复现的随机数来源。契约 §2 规则 8 本就要求概率条目按档位种子判定，基线同样用 `random.Random(seed)` 播种。
- **不控种时的差异**：`--no-seed` 关掉替换后，五档 5 次独立进程的 stdout 与 out JSON 都不再逐字节一致（`raw/sillytavern_determinism_native.txt`）。
  观测到的两个变动源是 uid17（概率判定）与 uid25（内容宏），见交付报告第 4.4 节。
- **锚点标定例外**：`--no-seed` 只关掉 6 个 turn 的档位读数；锚点搜索（决定本档 `maxContext`）始终控种，否则 `anchorUnbounded` 与各 `maxContext` 探测两次抽样不同，锚点不可比。

**预算口径（契约字符 vs ST token）**

- ST 的预算 = `Math.round(world_info_budget × maxContext / 100)`（`world-info.js:4736`），单位是 token；`world_info_budget` 保持 ST 默认 25%。
- **P0 的 maxContext ＝ 16384**，token 预算 **4096**。取值规则：在 P0 档位设置下，取最小的 2 的幂，使 6 个 turn 的注入集与「无约束注入」（maxContext=1000000）逐 turn 完全相同；实测 8192 仍构成约束、16384 通过（`raw/sillytavern_timing.txt` 的 `anchor_probe` 行）。
- **P3 的 maxContext ＝ 2458**，token 预算 **615**。取值规则：`round(16384 × 600 ÷ 4000)`，即按契约 §1.3 里 P3 与 P0 的预算比（600:4000）缩放锚点。
- P1／P2／P4 的 `budget_chars` 与 P0 同为 4000，共用锚点 16384。
- **P3 与基线的预算不可直接比字符数**：615 是 token，基线 600 是字符，两者只在量级上接近。可比的只有 dropped 条目集合——契约 M3 本就是集合口径。
- 两个 maxContext 都由上述规则从夹具与 ST 自己的分词器推出，没有为读数好看而手调。

## 七、适配器侧口径声明（契约未写死、由本适配器固定）

1. **chat 数组形状**：`world_info_include_names=false`，传给 `checkWorldInfo` 的是消息 `text` 反序数组（最新在前），与契约 §2 规则 1 的「窗口＝最近 N 条消息」对齐。
2. **inject_order**：＝引擎桶的稳定顺序 `before_char → at_depth → after_char`；桶内顺序取引擎自己拼好的 `worldInfoBefore`／`WIDepthEntries`／`worldInfoAfter` 里的先后（`:5203-5266`）。
3. **dropped_uids**：＝「无约束注入集（maxContext=1000000）− 本档注入集」。两次调用用同一 turn 种子，故概率与成组结果一致，差集只来自预算（含预算导致的递归提前停止）。
4. **概率、成组与内容宏可复现**：见第六节「控种口径」；这是适配器对契约 `seed` 字段的落地，不是改引擎算法，也不是自写触发逻辑。
5. **世界书文件位置**：`upstream/data/default-user/worlds/roleplay_eval.json` 与 `roleplay_eval_p0.json`。这两个文件由 `run.mjs` 每次重建，属被测方用户数据目录，不是源码改动。
6. **诊断开关**：`ST_DUMP_CONSOLE=1` 把 `[WI]` 调试行转写到 stderr；`ST_DUMP_CONTENT=1` 把注入正文转写到 stderr；`--emit-timing` 才打印 `TIMING` 行；`--no-seed` 关掉档位读数的控种（锚点仍控种）。缺省 stdout 只有 `CAPS`／`READOUT`／`UNSUPPORTED`／`ERROR` 与 `ENGINE_NOTE` 的确定性内容，保证逐次字节一致。
7. **服务复用**：`run.mjs` 先探测 `http://127.0.0.1:8123/`，已在监听就复用，否则 `node server.js --port 8123` 自起并等 HTTP 200。冷起耗时见第二节。

## 八、运行

```bash
cd bench/roleplay_eval/adapters/sillytavern
bash fetch_upstream.sh                      # codeload 取快照（下载实测 7 s，38,087,675 字节）
export CHROME_PATH="C:/Users/Zs/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe"
bash setup.sh                               # npm ci ＋ tests npm install（约 1 min，缓存已热 10 s）

cd ../../../..
python -X utf8 bench/roleplay_eval/harness/runner.py --adapter sillytavern --profiles P0,P1,P2,P3,P4
python -X utf8 bench/roleplay_eval/harness/validate.py bench/roleplay_eval/out/sillytavern_P0.json
python -X utf8 bench/roleplay_eval/harness/score.py --name sillytavern
node bench/roleplay_eval/adapters/sillytavern/verify_determinism.mjs --repeats 5
node bench/roleplay_eval/adapters/sillytavern/verify_determinism_native.mjs --repeats 5   # 原生（不控种）对照，约 96 s
```

只跑单档：

```bash
node bench/roleplay_eval/adapters/sillytavern/run.mjs \
  --data bench/roleplay_eval/data --profile P0 --out bench/roleplay_eval/out/sillytavern_P0.json
```

适配器只读 `--data`，只写 `--out` 与 `upstream/data/default-user/worlds/`。运行期零网络零凭据：只访问本地 server 与本机 chromium，不请求任何模型 API，不调用任何 LLM。

## 九、25 条条目的 ST 侧机制

| uid | 主要机制 | P0 读数里的表现 |
| --- | --- | --- |
| 1 | 常量 | 每 turn 注入 |
| 2 | 单键「林小满」 | turn1-2 命中 |
| 3 | 多键 OR | 与 uid2 同步 |
| 4 | 次选 AND_ANY | turn1 起命中 |
| 5 | 次选 AND_ALL | turn2 起（雨伞＋咖啡馆同窗） |
| 6 | 次选 NOT_ANY | 窗口无「警察」即命中 |
| 7 | 大小写不敏感 | turn6 命中（原文 LIN XIAOMAN） |
| 8 | 条目级全词 | P0 起命中（CJK 边界见第五节） |
| 9 | `scanDepth=1` | 只在最近 1 条含「咖啡馆」时命中 |
| 10 | `scanDepth=6` | turn2 起命中 |
| 11 | 大小写不敏感 | turn2-3 命中 |
| 12 | 递归源 | turn2-3 命中并带出 uid13 |
| 13 | 递归目标 | turn2-3 由 uid12 正文带出 |
| 14 | `excludeRecursion` | turn4 起直接命中 |
| 15/16 | 组 `props` 加权抽签 | turn3-4 由 uid15 胜出 |
| 17 | 概率 50 | 种子判定：P0 turn3-6 判不过；P2 turn3 判过 |
| 18/19 | `order` 200／10 | 两者都注入，顺序见 `inject_order` |
| 20 | 超长常量（900 字符） | P0 全注入；P3 被预算裁掉 |
| 21 | 末轮线索 | turn5-6 命中 |
| 22 | 停用 | 从不激活 |
| 23 | 空主键 × 选择性 | ST 与基线都判「无键即跳过」 |
| 24 | 正则键探针 | 键被解析为正则（`:2901`），但 `/地.图/` 需要 地、图 之间多一个字符，原文「地图」不匹配 |
| 25 | 内容宏探针 | 正文被 `substituteParams`（`:5058`）展开：`{{roll:d6}}`→1–6 的整数、`{{user}}`→`User`，39 字符变 25 字符。控种读数里观测到 3 种取值：`5`（P0/P1/P4 turn3）、`1`（P0/P1/P4 turn4）、`4`（P2 turn3）；该条不参与内容溯源 |
