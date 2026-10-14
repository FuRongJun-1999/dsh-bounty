# diceframe 适配器（角色扮演横评 · 世界书触发＋上下文预算）

被测对象：`diceframe/diceframe` commit `d2246e0d0d32867e8e090c238b588441bad96a28`（2026-10-14T05:46:36Z），
引擎版本 `src/version.py` 的 `__version__ = "2.6.1"`。

## 一、文件

| 文件 | 作用 |
| --- | --- |
| `fetch_upstream.sh` | 按锁定 sha 从 codeload 取源码到 `upstream/`（同目录 `.gitignore` 写 `upstream/` 与 `.venv/`：快照与虚拟环境不进版本库，`fetch_upstream.sh` / `setup.sh` 可重建） |
| `setup.sh` | 建 `.venv` 并用 Tsinghua 镜像装 `upstream/requirements.txt` + `pytest` + `pytest-asyncio` |
| `run.py` | 适配器主体：调 diceframe 真实模块算出契约输出，并向 stdout 打读数行 |
| `verify_determinism.py` | 同输入连跑 N 次，比对 stdout 与 out JSON 的 sha256，写 `raw/diceframe_determinism.txt` |
| `upstream/` | 只读源码快照（25 MB 级），由 `fetch_upstream.sh` 重建 |

版本与体积（本机实测，Windows 11 + MSYS2/Git-Bash，Python 3.13.13）：

| 项 | 实测值 |
| --- | --- |
| codeload 下载 + 解压 | 4 秒 |
| `python -m venv` | 5 秒 |
| `pip install`（Tsinghua 镜像，25 个包） | 52 秒 |
| `.venv` 体积 | 66001 KB（≈ 64.5 MiB） |
| `upstream/` 体积 | 25495 KB（≈ 24.9 MiB） |
| 压缩包 sha256 | `beaa511e409676e00a1db43d4b5fb360aea908b9d692529d2d2f6d9060b16d04` |

## 二、run.py 调用的 diceframe 代码

| 步骤 | 引擎入口 |
| --- | --- |
| 规范世界书 → 引擎条目 | `src/lorebook/importer.py` 的 `draft_lorebook_import`（格式探测后走 `src/lorebook/adapters/sillytavern.py:from_sillytavern`）与 `write_import_entries`（含 `import_entry_id` 生成 canonical id、`normalize_primary_match_mode` / `normalize_selective_logic` 归一化） |
| 激活 | `src/lorebook/matcher.py` 的 `KeywordMatcher.build`（:75）与 `match_with_recursive`（:101） |
| 概率门 | `src/lorebook/activation.py` 的 `evaluate_probability`（:90-95），经 `KeywordMatcher(rng=...)` 注入固定种子 |
| 预算与最终顺序 | `src/lorebook/retrieval.py` 的 `LoreRetriever._apply_budgets`（:800-825）→ `_merge_and_sort`（:626-636） |

适配器自己只做三件事：档位到引擎字段的注入、消息窗口文本的构造、读数序列化。

## 三、字段映射表（规范世界书 → diceframe 原生字段）

规范条目先写成引擎自带 ST 适配器认识的词汇，再由引擎的 `from_sillytavern` 与 `write_import_entries` 转成原生字段。

| 规范字段 | 送入 ST 形状 | 引擎原生字段 | 口径 |
| --- | --- | --- | --- |
| `uid` | `uid` | `external_id` → 条目 `id` | 引擎 `import_entry_id` 生成：`book:roleplay-eval-worldbook:entry:<sha256(uid)[:16]>` |
| `comment` | `comment` | `name` | 直通 |
| `content` | `content` | `content` | 直通；字符数、字节数、sha256 由 `harness/metrics.py` 量尺算 |
| `keys` | `keys` | `keywords` | 直通；键写成 `/…/` 形式时引擎按 Python 正则执行（`matcher.py:498-510`） |
| `secondary_keys` | `secondary_keys` | `secondary_keys` | 直通 |
| `selective` | `selective` | `selective` | 直通；`false` 时次选区不参与判定（`matcher.py:570`） |
| `selective_logic` | `selective_logic` | `selective_logic` | 引擎归一化：`and_any` / `and_all` / `not_any` / `not_all`，未知值回落 `and_any`（`activation.py:18-46`） |
| `enabled` | `disable`（取反） | `enabled` | 直通；`false` 条目被 `disabled` 门拒绝 |
| `constant` | `constant` | `is_constant` | 直通；常量不经关键词直接进候选（`matcher.py:182`） |
| `order` | `order` | `order` | 字段值直通；排序方向由引擎决定（见第五节） |
| `probability` | `probability` | `probability` | 直通；`<100` 时过一次注入 rng 的判定（`activation.py:90-95`） |
| `case_sensitive` | `caseSensitive` | `case_sensitive` | 引擎只有条目级开关；档位 P4 的值由适配器按条目 OR 进去 |
| `match_whole_words` | `matchWholeWords` | `match_whole_words` | 同上一行；引擎实现为 `(?<!\w)…(?!\w)`（`matcher.py:502-504`） |
| `group` | `group` | `groups` | 直通 |
| `group_weight` | `groupWeight` | `group_weight` | 直通；组内仲裁是加权随机（`matcher.py:721-734`），不是取最大权重 |
| `recursion.exclude` | `excludeRecursion` | `non_recursable` | 直通 |
| `recursion.prevent` | `preventRecursion` | `prevent_further_recursion` | 直通 |
| `recursion.delay` | `delayUntilRecursion` | `delay_until_recursion` | 直通 |
| （正文宏） | — | 无 | **映射不上** |
| `position` | `position` | `prompt_slot` | **映射不上** |
| `depth` | `depth` | 无 | **映射不上** |
| `capability_probe` | 不写入 | 无 | **映射不上** |

档位（`data/profiles.json`）到引擎的注入：

| 档位字段 | 适配器做法 | 引擎依据 |
| --- | --- | --- |
| `scan_depth` | 取窗口文本 = 最近 N 条消息的 `text` 拼接，作为 lexical query 传入 | 引擎无窗口字段；lexical query 由调用方给一段文本（`retrieval.py:184-190`）。窗口是调用方职责，不是引擎能力 |
| `recursive` | 每条目置 `_lorebook_recursive_scanning` | `retrieval.py:463-464` 读 book 级 `recursive_scanning`，`matcher.py:453` 用它决定是否扫父条目正文 |
| `budget_chars` | `_apply_budgets(activated, budget)` | 整体预算按字符估算（`budget.py:69-80`、`estimate_entry_chars`），超出者跳过并计入 omitted |
| `case_sensitive` / `whole_words` | 条目级 OR 注入 | 引擎无书级匹配口径开关 |
| `seed` | `KeywordMatcher(rng=random.Random(20261014).random)`，每 turn 重置 | 概率门与组内加权随机共用同一 rng 流 |
| `recursive_max_depth` | 不使用 | 引擎的递归边界来自 cycle guard、`max_steps` / `max_activated`、book 级开关与条目标志（`matcher.py:222-226`），无「最多 3 层」这一档位语义 |

## 四、映射不上 ⇒ unsupported（逐条原因）

| 字段 | reason（读数行用） | 依据 |
| --- | --- | --- |
| `depth` | `st-depth-in-engine-unmapped-fields` | 引擎自己的 ST 适配器把 `depth` 列进不建模字段（`sillytavern.py:21-28`），导入时只留在 `extensions`；因此条目级扫描窗口在引擎里不存在，uid9（depth=1）与 uid10（depth=6）都与档位窗口同宽 |
| `position` | `st-position-anchor-no-canonical-prompt-slot` | 引擎只接受 5 个 canonical slot 名（`sillytavern.py:12-17`）；`before_char` / `after_char` / `at_depth` 一律落空并计入警告，`prompt_slot` 只做标签不改变注入位置。读数的 `blocks[].position` 是夹具请求值的回填，不是引擎产出 |
| `capability_probe` | `fixture-marker-not-an-engine-field` | 夹具标记，引擎无对应字段；uid24（正则键）与 uid25（内容宏）分别按 `keys` 与 `content` 常规处理 |
| `macro_expand` | `engine-src-has-no-macro-expander` | `src/` 全库检索 `macro` 零命中，世界书正文的 `{{roll:d6}}` / `{{user}}` 原样保留 |

这四条是全部 unsupported；没有为凑数而列的条目。

## 五、适配器侧口径声明（契约未写死、由本适配器固定）

1. **注入顺序＝引擎的最终顺序**：`_apply_budgets` → `_merge_and_sort`，键为 `tier → order 升序 → 来源优先级 → 语义分 → id 字符串序`（`retrieval.py:610-624`）。同 tier 同 order 的先后由引擎生成的不透明 id 的字符串序决定（uid1 的 id 以 `6b86b273ff34fce1` 开头），这是引擎行为，不是适配器排序。
2. **模糊回退关**：引擎对 ST 导入书（`source_kind=device`）的 fuzzy 默认是关（`resolver.py:56-60`），适配器显式写 `_lorebook_fuzzy_enabled=False`。若打开，`matcher.py:174-181` 会在精确命中为空时用二元子串回退召回。
3. **`max_activated` 不收紧**：引擎调用方按预算推导候选上限，下界是 `MIN_BUDGET_CANDIDATES=32`；夹具 25 条低于该下界，故传 `None`（引擎默认 400）与传推导值等价。
4. **`current_tick=None`**：夹具无 `sticky` / `cooldown` / `delay`，`delay` 前置门按「调用方无 tick authority」跳过（`matcher.py:274-287`）。
5. **`extra_candidates=None`**：不接 embedding 通道（该通道未测，见报告第 6 节）。
6. **概率条目每 turn 重置种子**：与基线 §2 规则 8 的口径一致，使读数可复现。
7. **stdout 的 `ENGINE_NOTE` 行**是引擎自己的警告原文（ST 适配器对 `position` / `depth` 的告警），只作证据，不进读数。

## 六、运行

工作目录＝仓库根（含 `bench/` 的那一层）。

```bash
# 1. 取被测源码到 adapters/diceframe/upstream/（codeload 压缩包，锁定 sha）
cd bench/roleplay_eval/adapters/diceframe
bash fetch_upstream.sh

# 2. 建 .venv 并装依赖（Tsinghua 镜像；运行期不需要网络与凭据）
bash setup.sh
cd ../../../..

# 3. 跑适配器单档（工作目录＝仓库根）；解释器必须是第 2 步建好的 venv：系统 python 缺 diceframe 依赖，实测退出码 1
./bench/roleplay_eval/adapters/diceframe/.venv/Scripts/python.exe -X utf8 bench/roleplay_eval/adapters/diceframe/run.py \
  --data bench/roleplay_eval/data --profile P0 --out bench/roleplay_eval/out/diceframe_P0.json
```

实测（2026-10-14，Windows 11 + MSYS2/Git-Bash，Python 3.13.13）：第 1、2 步退出码 0（为不改动仓库内既有 `upstream/` 与 `.venv`，按脚本自带的目标目录参数在临时目录重跑；取回的 2183 个文件与仓库内快照逐文件 sha256 相同）。第 3 步的退出码随解释器变化：系统 `python` 为 1，stderr 末行为 `ERROR diceframe profile=- kind=engine-import-failed (No module named 'peewee')`；`.venv/Scripts/python.exe` 为 0。两次实测的完整输出见 `bench/roleplay_eval/raw/diceframe_repro_fix.txt`。

`run.py` 的 `--upstream` 缺省指向同目录的 `upstream/`，也可用环境变量 `DICEFRAME_UPSTREAM` 覆盖。
适配器只读 `--data`、只写 `--out`；运行期零网络、零凭据、零 LLM 调用。

## 七、25 条条目的引擎 id

下表为引擎 `import_entry_id` 对每条夹具条目生成的 canonical id 前缀（`book:roleplay-eval-worldbook:entry:` 之后 16 位十六进制）。

| uid | 引擎 id 前缀 | 主要机制 |
| --- | --- | --- |
| 1 | `6b86b273ff34fce1` | 常量 |
| 2 | `d4735e3a265e16ee` | 单键 |
| 3 | `4e07408562bedb8b` | 多键 OR |
| 4 | `4b227777d4dd1fc6` | 次选 and_any |
| 5 | `ef2d127de37b942b` | 次选 and_all |
| 6 | `e7f6c011776e8db7` | 次选 not_any |
| 7 | `7902699be42c8a8e` | 大小写（键小写） |
| 8 | `2c624232cdd22177` | 全词（条目级 true） |
| 9 | `19581e27de7ced00` | depth=1（unsupported） |
| 10 | `4a44dc15364204a8` | depth=6（unsupported） |
| 11 | `4fc82b26aecb47d2` | 大小写（原文大写） |
| 12 | `6b51d431df5d7f14` | 递归源 |
| 13 | `3fdba35f04dc8c46` | 递归目标 |
| 14 | `8527a891e2241369` | 递归排除 |
| 15 | `e629fa6598d73276` | 同组高权重 |
| 16 | `b17ef6d19c7a5b1e` | 同组低权重 |
| 17 | `4523540f1504cd17` | 概率 50 |
| 18 | `4ec9599fc203d176` | order=200 |
| 19 | `9400f1b21cb527d7` | order=10 |
| 20 | `f5ca38f748a1d6ea` | 超长常驻 |
| 21 | `6f4b6612125fb3a0` | 末轮线索 |
| 22 | `785f3ec7eb32f30b` | 停用 |
| 23 | `535fa30d7e25dd8a` | 空主键 |
| 24 | `c2356069e9d1e79c` | 正则键探针 |
| 25 | `b7a56873cd771f2c` | 宏探针 |

