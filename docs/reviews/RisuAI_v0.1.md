# RisuAI 角色扮演横评报告 v0.1

被测引擎：**RisuAI**（`kwaroran/Risuai`，GPL-3.0，TypeScript/Svelte）。
本报告全部读数来自本机真实执行日志，原始输出落在 `bench/roleplay_eval/raw/risuai_*`。
围栏块里的每一行都逐字取自对应 `raw/risuai_*.txt`；正文不含任何模型评分或主观措辞。

## 0. 结论摘要

1. **五档全部产出完整读数，契约校验全绿。** P0–P4 逐档 `harness/validate.py` 各 60 项检查、0 失败、退出码 0；注入块的 `chars`/`bytes`/`sha256` 与夹具正文逐字相同，加 `--strict-content` 仍全绿（M1、M8；`raw/risuai_P0.json`）。
2. **激活集与基线高度一致：P0 六轮里四轮完全相同。** 差异只出现在 turn3 与 turn4，独有条目恒为 uid16、uid17（M1；`raw/risuai_baseline_diff.txt` 的 `DIFF risuai baseline P0 turn=3 only_a=16,17 only_b=- same=8`）。Δ 口径：`M1_active_f1_delta` = −0.0393519，`M1_active_symdiff` = 0.666667（M1；`raw/risuai_kpi.txt`）。
3. **uid16、uid17 这两处差异可逐条归因到 unsupported 字段。** uid16 是成组择一的落选条目（上游 `loreBook` 无分组字段），uid17 是概率条目（上游装饰器用 `Math.random`，本适配器不使用，主键命中即注入）（M1、M8；`raw/risuai_P0.txt` 的 `UNSUPPORTED risuai field=group ...` 与 `UNSUPPORTED risuai field=probability ...`）。
4. **注入顺序是读数差异最大的一项。** 上游返回顺序为 `order` 升序，基线为 `order` 降序；同一激活集上方案侧逆序对数 25.6667，Δ = +22.8333（M2；`raw/risuai_kpi.txt`）。
5. **预算档的粗读数无差异，但单位不同。** P0→P3 两侧都只裁掉 uid20，dropped 对称差六轮全为 0，`M3_budget_dropped_delta` = 0（M3；`raw/risuai_diff.txt` 的 `... .dropped P0vsP3 turn=1 only_a=- only_b=20 same=0`）。上游预算计 token、契约计字符，`budget_chars` 进 unsupported；P3 档的激活集差异另计 2 条（uid16、uid17）（M3、M8；`raw/risuai_P0.txt` 的 `UNSUPPORTED risuai field=budget_chars ...`）。
6. **递归消融方向与基线一致。** 关递归后 P0 比 P1 多出的条目是 uid13，只出现在 turn2、turn3；`M4_recursion_ablation_delta` = 0，即两档之差与基线同幅（M4；`raw/risuai_diff.txt` 的 `DIFF risuai@P0 risuai@P1 P0vsP1 turn=2 only_a=13 only_b=- same=12`）。
7. **深度消融收缩明显。** P0→P2 方案侧对称差均值 4.5，基线侧 4.0，Δ = `M5_depth_ablation_delta` = 0.5；P2 档窗口只剩 1 条消息，六轮激活数之和降到 22（M5；`raw/risuai_kpi.txt`、`raw/risuai_P2.txt` 的 `READOUT risuai P2 turn=3 active=5 ...`）。
8. **确定性成立。** 五档各 8 次独立进程 stdout 全等（`repeats=8 identical=true`）；另单独连跑 5 次独立进程，out JSON 与 stdout 的 sha256 五次全同，且等于 `out/risuai_P0.json`（M6；`raw/risuai_repeat.txt`、`raw/risuai_determinism.txt`）。
9. **匹配口径消融是与基线分歧最大的一处。** 方案侧 P0→P4 对称差均值 5.8333，基线侧 3.8333，Δ = `M7_match_ablation_delta` = 2；P4 档方案侧六轮只剩 uid1、uid20（turn2、turn3 另多 uid11），基线仍保留 uid2、uid3、uid6、uid18、uid19（M7；`raw/risuai_baseline_diff.txt` 的 `DIFF risuai baseline P4 turn=1 only_a=- only_b=2,3,6,18,19 same=2`）。
10. **代价与零凭据可运行性。** 源码 41,703,593 字节 / 597 文件；依赖 909,970,803 字节 / 33,317 文件；单档端到端 p50 约 4.06–4.16 s，基线同档 p50 为 46.2834 ms（M8；`raw/risuai_timing.txt`、`raw/risuai_runner.txt` 的 `TIMING risuai profile=P0 ...`）。在 `node --permission` 且不给 `--allow-net` 下 rc=0，out sha256 与常规环境逐字节相同（M8；`raw/risuai_nonet.txt`）。

## 1. 被测对象与版本

| 项 | 值 | 依据 |
|---|---|---|
| 仓库 | `https://github.com/kwaroran/Risuai` | `raw/risuai_P0.json` 的 `upstream_repo` |
| commit | `454e5e207747399f43a4788f5f08ecd5aa291550` | `raw/risuai_P0.json` 的 `upstream_commit` |
| 许可 | GPL-3.0 | 仓库 `LICENSE` |
| 适配器版本 | `Risuai@454e5e2` | `raw/risuai_P0.json` 的 `adapter_version` |
| 适配器入口 | `bench/roleplay_eval/adapters/risuai/run.mjs` | `raw/risuai_P0.json` 的 `engine_env.entry` |
| 注入用例 | `bench/roleplay_eval/adapters/risuai/inject/rp67_adapter.test.ts` | 运行期复制到 `upstream/src/ts/poc/rp67_adapter.test.ts` |
| 被测算法 1 | `src/ts/process/lorebook.svelte.ts` 的 `loadLoreBookV3Prompt` | 触发 / 二级键 / 递归 / 预算 / 排序 |
| 被测算法 2 | `src/ts/tokenizer.ts` 的 `tokenize` | 被 `lorebook.svelte.ts:581` 调用 |
| 被测算法 3 | `src/ts/parser/parser.svelte.ts` 的 `risuChatParser` | 被 `lorebook.svelte.ts:581` 调用 |
| 被测算法 4 | `src/ts/process/prompt.ts` 的 `detectPromptJSONType` / `stChatConvert` | 注入用例直接调用 |
| 被测算法 5 | `src/ts/parser/chatML.ts` 的 `parseChatML` | 注入用例直接调用 |
| 运行期 | node `v24.16.0`；vitest `4.1.2`；pnpm `10.34.1` | `raw/risuai_timing.txt` |
| 上游快照核对 | `package.json` 的 git blob sha1 = `eeb47ce1606584e68265ef4e823873b6ee5951c0` | `raw/risuai_timing.txt` 的 `FETCH` 行 |

**唯一被替换的模块是全局状态容器 `src/ts/stores.svelte`**（提供 `DBState` / `selIdState` / `selectedCharID`）。
仓库自带测试 `src/ts/parser/tests/cbs/strings.test.ts:23-61` 用同一做法；原因是模块级 `$effect` 加循环导入在 vitest 的 SSR 转换下报
`Cannot read properties of undefined (reading 'selId')`（`src/ts/parser/parser.svelte.ts:463-465`）。
触发、匹配、递归、预算、排序、token 估算、CBS 求值全部走上游真代码，没有自写的等价算法。

## 2. 复现步骤

环境：Windows + MSYS2/Git-Bash；node `v24.16.0`；npm `11.13.0`；本机无 pnpm；python `3.13.13`。
下列命令从仓库克隆根开始，可原样粘贴执行。

```bash
cd "$(git rev-parse --show-toplevel)"
cd bench/roleplay_eval

bash adapters/risuai/fetch_upstream.sh
bash adapters/risuai/setup.sh

node adapters/risuai/run.mjs --data data --profile P0 --out out/risuai_P0.json
python -X utf8 harness/validate.py out/risuai_P0.json

python -X utf8 harness/runner.py --adapter risuai --profiles P0,P1,P2,P3,P4
python -X utf8 harness/score.py --name risuai

for p in P0 P1 P2 P3 P4; do python -X utf8 harness/validate.py out/risuai_$p.json; done

node adapters/risuai/run.mjs --data data --profile P0 --out out/risuai_P0.json --engine permissioned
```

- `fetch_upstream.sh` 用 codeload 取 `tar.gz/<sha>`（本机 git clone 常被重置），解到 `adapters/risuai/upstream/`，并核对 `package.json` 的 git blob sha1。实测 8 s、41,703,593 字节、597 文件。
- `setup.sh` 执行 `npx --yes pnpm@10.34.1 install --frozen-lockfile`。npm 路线不可用：`package.json` 的 `dependencies` 里写了仅适用 win32-arm64 的 `@tauri-apps/cli-win32-arm64-msvc`，`npm install` 以 EBADPLATFORM 结束。
- 本机 pnpm 内容寻址仓已有全部包，本次安装 11.5 s（pnpm 自报 6.2 s）；冷仓同机实测 74.0 s，见 `spike/risu-roleplay/SPIKE.md`。两者都记在 `raw/risuai_timing.txt`。
- 预期耗时：单档 `run.mjs` 约 4.1–5.2 s（含 npx 与 vitest 启动；vitest 自报 3.15 s）；`runner.py` 五档各 8 次，本机端到端 164.6 s；`score.py` 约 1 s。
- `--engine permissioned` 把同一批用例的调用方式换成 `node --permission --allow-fs-read=* --allow-fs-write=* --allow-worker --allow-addons --allow-child-process node_modules/vitest/vitest.mjs run src/ts/poc/rp67_adapter.test.ts`。`--allow-addons` 与 `--allow-child-process` 是加载已装原生模块与起 vitest 子进程所必需；`--allow-net` 未给，网络系统调用被拒。

## 3. 基线 vs 方案对照读数

| 读数 | 基线 | 方案（RisuAI） | 来源 |
|---|---|---|---|
| M1 P0 激活集 F1（对基线同 turn） | 1.000（自比） | 0.960648 | `raw/risuai_kpi.txt` |
| M1 Δ 口径 F1（方案 − 基线） | 0 | −0.0393519 | `raw/risuai_kpi.txt` |
| M1 P0 激活集对称差（逐 turn 均值） | 0 | 0.666667 | `raw/risuai_kpi.txt` |
| M2 同激活集逆序对数（方案侧均值） | — | 25.6667 | `raw/risuai_kpi.txt` |
| M2 Δ 逆序对（方案 − 基线） | 0 | +22.8333 | `raw/risuai_kpi.txt` |
| M3 P0/P3 的 dropped 对称差 Δ | 0 | 0 | `raw/risuai_kpi.txt` |
| M4 P0/P1 激活集对称差 Δ（递归） | 0 | 0 | `raw/risuai_kpi.txt` |
| M5 P0/P2 激活集对称差 Δ（深度） | 0 | 0.5 | `raw/risuai_kpi.txt` |
| M6 确定性（identical 均值，5 档） | — | 1 | `raw/risuai_kpi.txt` |
| M7 P0/P4 激活集对称差 Δ（匹配口径） | 0 | 2 | `raw/risuai_kpi.txt` |
| M8 五档激活条目数之和 | 170（逐档 READOUT 行求和） | 175 | `raw/risuai_kpi.txt`、`raw/risuai_P*.txt` |
| M8 单档端到端 P0 p50 | 46.2834 ms | 4157.86 ms | `raw/baseline_runner.txt`、`raw/risuai_runner.txt` |
| M8 依赖安装体积 | 0（仅标准库） | 909,970,803 字节 / 33,317 文件 | `raw/risuai_timing.txt` |

Δ 类 KPI 一律是「方案 − 基线」，由 `score.py` 按 (profile, turn) 配对后算；基线与方案同体时每条 Δ 恒为 0。
基线没有 `M2`/`M8` 的同类绝对量 KPI，表内基线列的 `M8` 两项分别由 `raw/baseline_P*.txt` 的 READOUT 行求和与 `raw/baseline_runner.txt` 的 TIMING 行读出。

`CAPS` 行（能力声明）：

```text
CAPS risuai {"recursive":true,"group":false,"probability":false,"regex_key":true,"at_depth":true,"whole_words_cjk":"no_match_cjk"}
```

## 4. 读数明细

### 4.1 P0 逐 turn READOUT（逐字取自 `raw/risuai_P0.txt`）

```text
READOUT risuai P0 turn=1 active=8 order=19,20,6,4,3,2,1,18 chars=1107 bytes=3297 dropped=-
READOUT risuai P0 turn=2 active=13 order=19,20,13,12,11,10,6,5,4,3,2,1,18 chars=1230 bytes=3666 dropped=-
READOUT risuai P0 turn=3 active=10 order=25,20,17,16,15,13,12,11,10,1 chars=1162 bytes=3442 dropped=-
READOUT risuai P0 turn=4 active=9 order=25,20,17,16,15,14,13,10,1 chars=1136 bytes=3364 dropped=-
READOUT risuai P0 turn=5 active=5 order=21,20,14,13,1 chars=1034 bytes=3102 dropped=-
READOUT risuai P0 turn=6 active=4 order=21,20,7,1 chars=1009 bytes=3027 dropped=-
```

### 4.2 P1–P4 逐 turn READOUT（逐字取自对应 `raw/risuai_P*.txt`）

```text
READOUT risuai P1 turn=1 active=8 order=19,20,6,4,3,2,1,18 chars=1107 bytes=3297 dropped=-
READOUT risuai P1 turn=2 active=12 order=19,20,12,11,10,6,5,4,3,2,1,18 chars=1202 bytes=3582 dropped=-
READOUT risuai P1 turn=3 active=9 order=25,20,17,16,15,12,11,10,1 chars=1134 bytes=3358 dropped=-
READOUT risuai P1 turn=4 active=9 order=25,20,17,16,15,14,13,10,1 chars=1136 bytes=3364 dropped=-
READOUT risuai P1 turn=5 active=5 order=21,20,14,13,1 chars=1034 bytes=3102 dropped=-
READOUT risuai P1 turn=6 active=4 order=21,20,7,1 chars=1009 bytes=3027 dropped=-
READOUT risuai P2 turn=1 active=2 order=20,1 chars=956 bytes=2868 dropped=-
READOUT risuai P2 turn=2 active=4 order=20,11,10,1 chars=1002 bytes=3006 dropped=-
READOUT risuai P2 turn=3 active=5 order=25,20,17,10,1 chars=1042 bytes=3082 dropped=-
READOUT risuai P2 turn=4 active=5 order=20,14,13,10,1 chars=1031 bytes=3093 dropped=-
READOUT risuai P2 turn=5 active=3 order=21,20,1 chars=980 bytes=2940 dropped=-
READOUT risuai P2 turn=6 active=3 order=20,7,1 chars=985 bytes=2955 dropped=-
READOUT risuai P3 turn=1 active=7 order=19,6,4,3,2,1,18 chars=207 bytes=597 dropped=20
READOUT risuai P3 turn=2 active=12 order=19,13,12,11,10,6,5,4,3,2,1,18 chars=330 bytes=966 dropped=20
READOUT risuai P3 turn=3 active=9 order=25,17,16,15,13,12,11,10,1 chars=262 bytes=742 dropped=20
READOUT risuai P3 turn=4 active=8 order=25,17,16,15,14,13,10,1 chars=236 bytes=664 dropped=20
READOUT risuai P3 turn=5 active=4 order=21,14,13,1 chars=134 bytes=402 dropped=20
READOUT risuai P3 turn=6 active=3 order=21,7,1 chars=109 bytes=327 dropped=20
READOUT risuai P4 turn=1 active=2 order=20,1 chars=956 bytes=2868 dropped=-
READOUT risuai P4 turn=2 active=3 order=20,11,1 chars=981 bytes=2943 dropped=-
READOUT risuai P4 turn=3 active=3 order=20,11,1 chars=981 bytes=2943 dropped=-
READOUT risuai P4 turn=4 active=2 order=20,1 chars=956 bytes=2868 dropped=-
READOUT risuai P4 turn=5 active=2 order=20,1 chars=956 bytes=2868 dropped=-
READOUT risuai P4 turn=6 active=2 order=20,1 chars=956 bytes=2868 dropped=-
```

### 4.3 方案 vs 基线逐 (profile, turn) 激活集 DIFF（逐字取自 `raw/risuai_baseline_diff.txt`）

```text
# score.py baseline-diff name=risuai baseline=baseline profiles=P0,P1,P2,P3,P4 metric=active_uids
# 行语法 DIFF <a> <b> <profile> turn=<k> only_a=<uids> only_b=<uids> same=<n>；a=risuai b=baseline；空集合写 -
# only_a=a 侧独有 only_b=b 侧独有 same=交集大小
DIFF risuai baseline P0 turn=1 only_a=- only_b=- same=8
DIFF risuai baseline P0 turn=2 only_a=- only_b=- same=13
DIFF risuai baseline P0 turn=3 only_a=16,17 only_b=- same=8
DIFF risuai baseline P0 turn=4 only_a=16,17 only_b=- same=7
DIFF risuai baseline P0 turn=5 only_a=- only_b=- same=5
DIFF risuai baseline P0 turn=6 only_a=- only_b=- same=4
DIFF risuai baseline P1 turn=1 only_a=- only_b=- same=8
DIFF risuai baseline P1 turn=2 only_a=- only_b=- same=12
DIFF risuai baseline P1 turn=3 only_a=16,17 only_b=- same=7
DIFF risuai baseline P1 turn=4 only_a=16,17 only_b=- same=7
DIFF risuai baseline P1 turn=5 only_a=- only_b=- same=5
DIFF risuai baseline P1 turn=6 only_a=- only_b=- same=4
DIFF risuai baseline P2 turn=1 only_a=- only_b=- same=2
DIFF risuai baseline P2 turn=2 only_a=- only_b=- same=4
DIFF risuai baseline P2 turn=3 only_a=17 only_b=- same=4
DIFF risuai baseline P2 turn=4 only_a=- only_b=- same=5
DIFF risuai baseline P2 turn=5 only_a=- only_b=- same=3
DIFF risuai baseline P2 turn=6 only_a=- only_b=- same=3
DIFF risuai baseline P3 turn=1 only_a=- only_b=- same=7
DIFF risuai baseline P3 turn=2 only_a=- only_b=- same=12
DIFF risuai baseline P3 turn=3 only_a=16,17 only_b=- same=7
DIFF risuai baseline P3 turn=4 only_a=16,17 only_b=- same=6
DIFF risuai baseline P3 turn=5 only_a=- only_b=- same=4
DIFF risuai baseline P3 turn=6 only_a=- only_b=- same=3
DIFF risuai baseline P4 turn=1 only_a=- only_b=2,3,6,18,19 same=2
DIFF risuai baseline P4 turn=2 only_a=11 only_b=2,3,6,18,19 same=2
DIFF risuai baseline P4 turn=3 only_a=11 only_b=- same=2
DIFF risuai baseline P4 turn=4 only_a=- only_b=- same=2
DIFF risuai baseline P4 turn=5 only_a=- only_b=- same=2
DIFF risuai baseline P4 turn=6 only_a=- only_b=- same=2
```

读法：P0 六轮里 turn1/turn2/turn5/turn6 两侧集合完全相同；turn3、turn4 的 `only_a=16,17` 是方案侧独有条目，对应 §0 第 3 条的两处 unsupported。P4 档方向相反，`only_b` 列出基线独有、方案侧不命中的条目。

### 4.4 消融 DIFF（绝对幅度，逐字取自 `raw/risuai_diff.txt`）

```text
# score.py ablation-diff name=risuai baseline=baseline profiles=P0,P1,P2,P3,P4
# a=<name>@<high> b=<name>@<low> profile=<high>vs<low>；横轴=同名方案两档之间的差异
# P0vsP3=budget（active 口径另加一行 .dropped 口径） P0vsP1=recursive P0vsP2=scan_depth P0vsP4=match_profile
# 行语法同 baseline-diff；空集合写 -
DIFF risuai@P0 risuai@P3 P0vsP3 turn=1 only_a=20 only_b=- same=7
DIFF risuai@P0.dropped risuai@P3.dropped P0vsP3 turn=1 only_a=- only_b=20 same=0
DIFF risuai@P0 risuai@P3 P0vsP3 turn=2 only_a=20 only_b=- same=12
DIFF risuai@P0.dropped risuai@P3.dropped P0vsP3 turn=2 only_a=- only_b=20 same=0
DIFF risuai@P0 risuai@P3 P0vsP3 turn=3 only_a=20 only_b=- same=9
DIFF risuai@P0.dropped risuai@P3.dropped P0vsP3 turn=3 only_a=- only_b=20 same=0
DIFF risuai@P0 risuai@P3 P0vsP3 turn=4 only_a=20 only_b=- same=8
DIFF risuai@P0.dropped risuai@P3.dropped P0vsP3 turn=4 only_a=- only_b=20 same=0
DIFF risuai@P0 risuai@P3 P0vsP3 turn=5 only_a=20 only_b=- same=4
DIFF risuai@P0.dropped risuai@P3.dropped P0vsP3 turn=5 only_a=- only_b=20 same=0
DIFF risuai@P0 risuai@P3 P0vsP3 turn=6 only_a=20 only_b=- same=3
DIFF risuai@P0.dropped risuai@P3.dropped P0vsP3 turn=6 only_a=- only_b=20 same=0
DIFF risuai@P0 risuai@P1 P0vsP1 turn=1 only_a=- only_b=- same=8
DIFF risuai@P0 risuai@P1 P0vsP1 turn=2 only_a=13 only_b=- same=12
DIFF risuai@P0 risuai@P1 P0vsP1 turn=3 only_a=13 only_b=- same=9
DIFF risuai@P0 risuai@P1 P0vsP1 turn=4 only_a=- only_b=- same=9
DIFF risuai@P0 risuai@P1 P0vsP1 turn=5 only_a=- only_b=- same=5
DIFF risuai@P0 risuai@P1 P0vsP1 turn=6 only_a=- only_b=- same=4
DIFF risuai@P0 risuai@P2 P0vsP2 turn=1 only_a=2,3,4,6,18,19 only_b=- same=2
DIFF risuai@P0 risuai@P2 P0vsP2 turn=2 only_a=2,3,4,5,6,12,13,18,19 only_b=- same=4
DIFF risuai@P0 risuai@P2 P0vsP2 turn=3 only_a=11,12,13,15,16 only_b=- same=5
DIFF risuai@P0 risuai@P2 P0vsP2 turn=4 only_a=15,16,17,25 only_b=- same=5
DIFF risuai@P0 risuai@P2 P0vsP2 turn=5 only_a=13,14 only_b=- same=3
DIFF risuai@P0 risuai@P2 P0vsP2 turn=6 only_a=21 only_b=- same=3
DIFF risuai@P0 risuai@P4 P0vsP4 turn=1 only_a=2,3,4,6,18,19 only_b=- same=2
DIFF risuai@P0 risuai@P4 P0vsP4 turn=2 only_a=2,3,4,5,6,10,12,13,18,19 only_b=- same=3
DIFF risuai@P0 risuai@P4 P0vsP4 turn=3 only_a=10,12,13,15,16,17,25 only_b=- same=3
DIFF risuai@P0 risuai@P4 P0vsP4 turn=4 only_a=10,13,14,15,16,17,25 only_b=- same=2
DIFF risuai@P0 risuai@P4 P0vsP4 turn=5 only_a=13,14,21 only_b=- same=2
DIFF risuai@P0 risuai@P4 P0vsP4 turn=6 only_a=7,21 only_b=- same=2
```

- 预算轴 `P0vsP3`：`active` 口径每轮都是 `only_a=20 only_b=-`（uid20 是 900 字符常驻条目）；`dropped` 口径每轮都是 `only_a=- only_b=20 same=0`，即两侧裁掉的是同一条目。
- 递归轴 `P0vsP1`：turn2、turn3 的 `only_a=13` 是关掉递归扫描后消失的条目；turn1、turn4、turn5、turn6 完全一致。
- 深度轴 `P0vsP2`：窗口从 4 条降到 1 条，逐轮独有条目数 6/9/5/4/2/1。
- 匹配口径轴 `P0vsP4`：逐轮独有条目数 6/10/7/7/3/2，是本适配器四组消融里幅度最大的一组。

### 4.5 KPI（逐字取自 `raw/risuai_kpi.txt`）

```text
# score.py kpi name=risuai baseline=baseline profiles=P0,P1,P2,P3,P4 bootstrap_iters=2000 bootstrap_seed=0 alpha=0.05
# 配对单位=(profile,turn)；Δ 类 KPI（名字含 _delta）= 方案 − 基线；n<2 时 ci=[-,-]
KPI M1_active_f1 value=0.960648 ci=[0.918981,1] n=6
KPI M1_active_f1_delta value=-0.0393519 ci=[-0.0810185,0] n=6
KPI M1_active_symdiff value=0.666667 ci=[0,1.33333] n=6
KPI M2_order_inv value=25.6667 ci=[12.5,44] n=6
KPI M2_order_inv_delta value=22.8333 ci=[11.6667,37.6667] n=6
KPI M3_budget_dropped_delta value=0 ci=[0,0] n=6
KPI M4_recursion_ablation_delta value=0 ci=[0,0] n=6
KPI M5_depth_ablation_delta value=0.5 ci=[0,1.16667] n=6
KPI M6_determinism value=1 ci=[1,1] n=5
KPI M7_match_ablation_delta value=2 ci=[0.5,3.5] n=6
KPI M8_total_active_uids value=175 ci=[140,212] n=30
```

### 4.6 字段映射条目数与被标 unsupported 的字段

规范世界书字段到 RisuAI `loreBook` 原生字段的映射表共 **25 条**，档位字段到 `loreSettings` 的映射表共 **9 条**，合计 34 条；其中可表达 23 条，不能表达、进 `unsupported` 的字段 **10 个**（世界书级 7 个加档位级 4 个，`case_sensitive` 两侧同名只计一次）。两张表连同依据行号在 `bench/roleplay_eval/adapters/risuai/README.md`。

被标 `unsupported` 的字段清单（逐字取自 `raw/risuai_P0.txt`）：

```text
UNSUPPORTED risuai field=probability reason=upstream-decorator-uses-Math.random-lorebook.svelte.ts:494
UNSUPPORTED risuai field=case_sensitive reason=upstream-folds-case-unconditionally-lorebook.svelte.ts:182
UNSUPPORTED risuai field=group reason=no-group-field-in-loreBook-database.svelte.ts:1338
UNSUPPORTED risuai field=group_weight reason=no-group-field-in-loreBook-database.svelte.ts:1338
UNSUPPORTED risuai field=recursion.prevent reason=no-upstream-field
UNSUPPORTED risuai field=recursion.delay reason=no-upstream-field
UNSUPPORTED risuai field=capability_probe reason=fixture-side-marker-no-upstream-field
UNSUPPORTED risuai field=budget_chars reason=upstream-budget-counts-tokens-not-chars
UNSUPPORTED risuai field=recursive_max_depth reason=upstream-loops-to-fixpoint-without-depth-cap
UNSUPPORTED risuai field=seed reason=no-effect-because-probability-unsupported
```

判据摘要：`probability` 走 `Math.random`（`lorebook.svelte.ts:494`）破坏可复现性；`case_sensitive` 在类型里有 `extentions.risu_case_sensitive`（`database.svelte.ts:1347-1349`）但触发路径不读它，匹配一律 `toLocaleLowerCase`（`:182-183`）；`group` 与 `group_weight` 在 `loreBook` 里无字段（`database.svelte.ts:1338-1359`）；`recursion.prevent` 与 `recursion.delay` 无对应字段或装饰器；`capability_probe` 是夹具侧标记；`budget_chars` 的单位是字符而上游计 token（`:581`、`:619-625`）；`recursive_max_depth` 上游是跑到不动点的 `while` 循环（`:259-611`），没有层数上限；`seed` 只服务概率判定，概率已 unsupported。

可表达的 23 条里值得单列三条：`and_all` 二级键用逐行 `@@additional_keys`（`:444-450`）表达成多条必须命中的正向查询；`not_any` 用 `@@exclude_keys`（`:451-457`）表达成负向查询；正则键用 `loreBook.useRegex` 加 `/pattern/flags` 键串（`:145-177`）。

正则键的可激活性是实测的，不是读代码推的。夹具 uid24 的键是 `/地.图/`，正则语义要求 `地` 与 `图` 之间再有一个字符，而夹具窗口里的正文只有「地图」两字，因此 uid24 在五档里都不激活（基线的字面比较同样不命中，故该条目不出现在 §4.3 的任何 DIFF 行里）。能力本身由正对照证明，`raw/risuai_P0.txt` 的 `EXTRA` 行头 200 字符：

```text
EXTRA risuai P0 matchlog=7,14,12,7,3,2 pos_raw=uid6:after_desc,uid4:after_desc,uid10:depth,uid6:after_desc,uid5:after_desc,uid4:after_desc,uid10:depth,uid10:depth prompt_diff=- uid25_roll_cbs_expanded
```

其中 `regex_key_probe_hits=[1,0]` 读作「三字窗口命中数为 1、两字窗口命中数为 0」，即同一条 `useRegex` 条目在「这里标着地标图。」下激活、在「我把地图折好塞进背包。」下不激活。`capabilities.regex_key` 因此记为 `true`。

### 4.7 确定性

`runner.py` 每档跑 1 次预热加 7 次采样，每次采样是独立进程，比较 stdout 的 sha256（逐字取自 `raw/risuai_repeat.txt`）：

```text
# adapter=risuai warmup=1 samples=7
# profile=P0
DETERMINISM risuai repeats=8 identical=true sha=6fc15aeecf08590cedbaeeeed3604e738e1c95458bf367ee5a1410690a504784
# profile=P1
DETERMINISM risuai repeats=8 identical=true sha=e94a9bc78ebde6f2c51a01e017cd1e69ce2f87045d177034d9bbd3fca2506077
# profile=P2
DETERMINISM risuai repeats=8 identical=true sha=ce1c0ac35045afa89d12ea63d1546948cd3b487d9f1f28f6f3391353131dd592
# profile=P3
DETERMINISM risuai repeats=8 identical=true sha=a99a03def2a86ec08132dcface8f87adc019fa214fd9d0800e49591d4c568f19
# profile=P4
DETERMINISM risuai repeats=8 identical=true sha=77440788a90d1687eab87cb855853799477c2eb57e8f5782a2ea2ac909372ed4
```

另在 `raw/risuai_determinism.txt` 记录 5 次独立进程（每次都新起 `node adapters/risuai/run.mjs`）的 out JSON 与 stdout 摘要：

```text
DETRUN run=1 rc=0 out_sha256=2695853eecc20558546c7373781288ffa9282b69357da381878abc60ab3b0622 stdout_sha256=6fc15aeecf08590cedbaeeeed3604e738e1c95458bf367ee5a1410690a504784
DETRUN run=2 rc=0 out_sha256=2695853eecc20558546c7373781288ffa9282b69357da381878abc60ab3b0622 stdout_sha256=6fc15aeecf08590cedbaeeeed3604e738e1c95458bf367ee5a1410690a504784
DETRUN run=3 rc=0 out_sha256=2695853eecc20558546c7373781288ffa9282b69357da381878abc60ab3b0622 stdout_sha256=6fc15aeecf08590cedbaeeeed3604e738e1c95458bf367ee5a1410690a504784
DETRUN run=4 rc=0 out_sha256=2695853eecc20558546c7373781288ffa9282b69357da381878abc60ab3b0622 stdout_sha256=6fc15aeecf08590cedbaeeeed3604e738e1c95458bf367ee5a1410690a504784
DETRUN run=5 rc=0 out_sha256=2695853eecc20558546c7373781288ffa9282b69357da381878abc60ab3b0622 stdout_sha256=6fc15aeecf08590cedbaeeeed3604e738e1c95458bf367ee5a1410690a504784
DETREF out/risuai_P0.json sha256=2695853eecc20558546c7373781288ffa9282b69357da381878abc60ab3b0622
```

### 4.8 代价

各档 TIMING 与确定性行（逐字取自 `raw/risuai_runner.txt`）：

```text
TIMING risuai profile=P0 min_ms=4101.29 p50_ms=4157.86 p95_ms=4193.69
DETERMINISM risuai repeats=8 identical=true sha=6fc15aeecf08590cedbaeeeed3604e738e1c95458bf367ee5a1410690a504784
TIMING risuai profile=P1 min_ms=4081.13 p50_ms=4126.73 p95_ms=4146.57
DETERMINISM risuai repeats=8 identical=true sha=e94a9bc78ebde6f2c51a01e017cd1e69ce2f87045d177034d9bbd3fca2506077
TIMING risuai profile=P2 min_ms=4007.95 p50_ms=4043.87 p95_ms=4121.57
DETERMINISM risuai repeats=8 identical=true sha=ce1c0ac35045afa89d12ea63d1546948cd3b487d9f1f28f6f3391353131dd592
TIMING risuai profile=P3 min_ms=4039.19 p50_ms=4096.53 p95_ms=4256.69
DETERMINISM risuai repeats=8 identical=true sha=a99a03def2a86ec08132dcface8f87adc019fa214fd9d0800e49591d4c568f19
TIMING risuai profile=P4 min_ms=4038.68 p50_ms=4095.37 p95_ms=4129.73
DETERMINISM risuai repeats=8 identical=true sha=77440788a90d1687eab87cb855853799477c2eb57e8f5782a2ea2ac909372ed4
```

基线 P0 同口径计时行（逐字取自 `raw/baseline_runner.txt`）：

```text
TIMING baseline profile=P0 min_ms=44.4012 p50_ms=46.2834 p95_ms=66.0251
```

依赖与安装实测（逐字取自 `raw/risuai_timing.txt`）：

```text
# RisuAI 适配器 M8 代价读数（本机实测）
# 机器：Windows + MSYS2/Git-Bash；node v24.16.0；npm 11.13.0；python 3.13.13；本机无 pnpm
UPSTREAM commit=454e5e207747399f43a4788f5f08ecd5aa291550
FETCH url=https://codeload.github.com/kwaroran/Risuai/tar.gz/454e5e207747399f43a4788f5f08ecd5aa291550
FETCH tgz_bytes=41703593 blob_ok_package.json=eeb47ce1606584e68265ef4e823873b6ee5951c0 upstream_files_excl_node_modules=597 wall_s=8
SETUP cmd=npx --yes pnpm@10.34.1 install --frozen-lockfile rc=0 wall_ms=11500 pnpm_self_report=6.2s pnpm_entries=425 store=warm
SETUP_NOTE 本机 pnpm 内容寻址仓已有全部包（尖兵同机装过一次），故本次 11.5 s；冷仓同机实测见 spike/risu-roleplay/SPIKE.md 的 74.0 s
NODE_MODULES bytes=909970803 files=33317 mib=867.8
UPSTREAM_TOTAL bytes=1016041177 files=33916 mib=969.0
NONET engine=node--permission-no-allow-net rc=0 out_sha256=2695853eecc20558546c7373781288ffa9282b69357da381878abc60ab3b0622 ref_sha256=2695853eecc20558546c7373781288ffa9282b69357da381878abc60ab3b0622
VITEST selftest_stdout=Test Files 1 passed (1) / Tests 2 passed (2) / Duration 3.15s (transform 2.01s, setup 25ms, import 2.34s, tests 392ms, environment 268ms)
VITEST engine_cmd=npx --no-install vitest run src/ts/poc/rp67_adapter.test.ts
VITEST run=1 rc=0 wall_ms=4561
VITEST run=2 rc=0 wall_ms=4937
VITEST run=3 rc=0 wall_ms=5246
RUNNER cmd=python -X utf8 harness/runner.py --adapter risuai --profiles P0,P1,P2,P3,P4 wall_s=164.6 repeats_per_profile=8
```

### 4.9 零网络复跑

`raw/risuai_nonet.txt` 是 `--engine permissioned` 的完整 stdout，末三行：

```text
NONET rc=0
NONET out_sha256=2695853eecc20558546c7373781288ffa9282b69357da381878abc60ab3b0622
NONET ref_sha256=2695853eecc20558546c7373781288ffa9282b69357da381878abc60ab3b0622
```

即在该次运行里，网络系统调用被 Node 权限模型拒绝的前提下，`run.mjs` 退出码 0，产出的 out JSON sha256 与常规环境的 `out/risuai_P0.json` 完全相同。本机未做物理断网或防火墙隔离验证，这一点写在 §5。

## 5. 不适用条件

本节列出本报告读数不能外推的情形。

1. **提交与代码路径**：全部读数绑定 commit `454e5e207747399f43a4788f5f08ecd5aa291550`。上游若改动 `lorebook.svelte.ts` 的匹配、排序或预算逻辑，第 4 节的读数与字段映射同时失效；换 commit 必须重跑而不是沿用本报告。
2. **夹具范围**：§4 的逐条差异只对 `data/worldbook.json`、`data/chat.jsonl`、`data/profiles.json` 这一组夹具成立。uid16 与 uid17 的差异、P4 档的全词行为都依赖这份夹具的键与正文，换夹具要重测。
3. **读数覆盖面**：本适配器只覆盖世界书触发与 token 预算这一面。上游把 `actives` 拼成最终 messages 的代码在 `src/ts/process/index.svelte.ts`，本报告不覆盖它；因此 `inject_order` 不能等同于最终消息数组里的位置。
4. **单位不可换算**：`budget_chars` 与上游 `tokenBudget` 单位不同。P3 档是「把 600 这个数直接喂给 token 预算」，不是「600 字符预算」。§3 的 M3 读数只在「两侧都裁同一条目」这一意义上可比。
5. **平台与 ICU**：匹配走 `toLocaleLowerCase`，其行为取决于 ICU 版本；token 估算走 `@dqbd/tiktoken` 的 `o200k_base` 词表，其内容随包版本变化。本报告只验证同一台机器、同一 Node 版本上的跨进程一致，不构成跨操作系统或跨 Node 版本的逐字一致结论。
6. **替换边界**：`src/ts/stores.svelte` 用测试替身，本报告不覆盖该容器自身的响应式行为，也不覆盖真实数据库初始化链路。
7. **零网络的证明方式**：零网络结论来自 Node 权限模型拒绝网络系统调用，不是物理断网或防火墙隔离。
8. **依赖体积口径**：`node_modules` 是全量锁定安装，未做依赖裁剪；「最小依赖足迹」不在本报告范围内。

## 6. 未测项与原因

以下各项在本次交付中**未测**，逐条给原因。凡在 `out/risuai_*.json` 的 `unsupported` 里出现的字段，全部在此列名。

1. **最终消息数组组装（未测）**：上游把世界书命中的 `actives` 拼进 system prompt、按 `FormatingOrder` 排列、裁掉超出上下文的 chat 的逻辑在 `src/ts/process/index.svelte.ts`。原因：该文件与请求发送、UI 状态、插件系统耦合，构造可运行 fixture 的成本超出本次交付边界。本报告的 `inject_order` 只到 `loadLoreBookV3Prompt` 返回数组为止。
2. **`runTrigger` 触发器脚本执行（未测）**：`src/ts/process/triggers.ts:1058` 的 `runTrigger` 是单个 114 KB 函数，同时引入请求层（`requestChatData`）、图像层（`generateAIImage`）、脚本层、内存层。原因：要构造可运行 fixture 必须同时伪造这四层，其中请求层与图像层必然离开本机，与零网络约束冲突。
3. **`@@probability`（未测）**：装饰器实现用 `Math.random()`（`lorebook.svelte.ts:493-498`），同一输入多次运行结果不同。原因：使用它会破坏本次交付的确定性判据（§4.7）。因此夹具 uid17 的 `probability=50` 在本适配器里不生效，该条目只要主键命中就注入，这处差异如实记为 `UNSUPPORTED risuai field=probability ...`。
4. **`@@keep_activate_after_match` 与 `@@dont_activate_after_match`（未测）**：两者写 chatvar（`lorebook.svelte.ts:588-593`、`:332-351`），跨次运行不幂等。原因同第 3 条。本适配器不使用它们。
5. **gemma / gemini tokenizer 分支（未测）**：`tokenizer.ts:295-297` 的 `geminiTokenizer` 走 `globalFetch` 打 `generativelanguage.googleapis.com` 并带访问令牌，`:257-264` 的 `gemmaTokenize` 与 `:336`、`:352` 走 HTTP 路径取词表。原因：零网络与零凭据约束下必然失败。本适配器固定 `db.aiModel='openrouter'`、`db.customTokenizer=''`，走 `:105` 到 `:131-133` 的本地 tiktoken 分支。
6. **HypaV3 与 embedding 检索（未测）**：原因：需要模型权重或外部 API，违反零凭据约束；这也是同方向另外两份交付的范围，本次刻意不相交。
7. **真实 LLM 面（未测）**：模型调用、采样、流式返回、错误重试。原因：本次交付是确定性面横评，运行期禁止联网、禁止调用任何 LLM，`engine_env` 相应记为 `network=none`、`llm=none`。
8. **`probability`（未测，见第 3 条）与 `case_sensitive`（未测：类型里有 `extentions.risu_case_sensitive`，但 `loadLoreBookV3Prompt` 不读它，`:182-183` 一律折叠大小写，因此 P4 档的大小写部分在 RisuAI 侧无效果）。**
9. **`group`（未测：`loreBook` 无分组字段，uid15 与 uid16 同组择一在 RisuAI 侧不发生）与 `group_weight`（未测：同上，权重无处安放）。**
10. **`recursion.prevent`（未测：无对应字段或装饰器，夹具中该值恒为 `false`）、`recursion.delay`（未测：同上）、`capability_probe`（未测：夹具侧标记，非引擎字段）。**
11. **`budget_chars`（未测：上游预算单位是 token 而不是字符，字符预算无法在不改上游代码的前提下表达；映射取同数值直传）、`recursive_max_depth`（未测：上游递归是跑到不动点的 `while` 循环，没有「最多 3 层」这种写法）、`seed`（未测：概率判定用 `Math.random`，不接受种子）。**
12. **角色卡导入导出链路（未测）**：`src/ts/characterCards.ts` 与 `src/ts/characters.ts`。原因：与文件选择器、UI 告警耦合，且不在上下文组装边界内。
13. **跨操作系统与跨 Node 版本的逐字一致（未测）**：原因见 §5 第 5 条，本次只验证同一台机器上的跨进程一致。
14. **依赖裁剪后的最小足迹（未测）**：`node_modules` 是全量锁定安装；`--filter` 或手工最小依赖集未试。
15. **npm 路线的替代绕法（未测）**：`--force`、`--os`/`--cpu` 覆盖、删掉 arm64 依赖再装都未验证；pnpm 路线与仓库 `packageManager` 字段一致，已足够。
16. **`svelte-check` 与 `vite build`（未测）**：与确定性读数无关，且耗时远大于读数本身。
