# diceframe 角色扮演横评报告 v0.1

## 0. 结论摘要

- M1 激活集：P0 六轮里 4 轮与基线一致，2 轮出现差异。turn1（`same=8`）、turn5（`same=5`）、turn6（`same=4`）集合相同；turn2 方案独有 uid9，turn3 方案独有 uid9/uid16、基线独有 uid15，turn4 方案独有 uid16、基线独有 uid10/uid15。逐条差异见 `raw/diceframe_baseline_diff.txt`。
- M1 归因：uid9（夹具 depth=1）与 uid10（夹具 depth=6）的差异来自「条目级扫描窗口」这一字段——引擎不建模该字段（见第 6 节 `depth`），两条都按档位窗口判定；uid15/uid16 的差异来自同组仲裁规则不同——引擎是加权随机（rng 控种），基线是取最大权重。
- M2 注入顺序：引擎按 `order` 升序注入候选，随后用不透明 id 字符串序收尾；基线按 `order` 降序。P0 turn1 方案 `order=19,4,3,1,2,6,20,18`，基线 `order=18,1,2,3,4,6,20,19`；同激活集上的逆序对数 M2_order_inv_delta=8.5，95% CI=[2.83333,17.5]，n=6。
- M3 预算溢出：P3（budget_chars=600）下引擎六轮都把 uid20（超长常驻）跳过并记为 dropped，其他条目全部保留；M3_budget_dropped_delta=0，CI=[0,0]，n=6，与基线的「跳过不截断」结果同幅。
- M4 递归消融：P0 与 P1 只在 turn2、turn3 差一条 uid13（递归目标）。引擎的递归开关是 book 级 `recursive_scanning`，打开时 uid12 的正文里的「灯塔」带出 uid13，同时 uid14 因 `non_recursable` 被拒；M4_recursion_ablation_delta=0，CI=[0,0]，n=6。
- M5 深度消融：P0 与 P2（scan_depth=1）六轮全部有差，差集含 uid2/3/4/5/6/9/10/11/12/13/16/18/19/21/25；M5_depth_ablation_delta=0.666667，CI=[0,1.33333]，n=6。
- M6 确定性：同输入连跑 5 次，stdout 与 out JSON 的 sha256 逐字节一致（5 个档位全部 identical=true）；runner 的 8 次重复给出同一组 sha。M6_determinism value=1，CI=[1,1]，n=5。
- M7 匹配口径：P0 与 P4（case_sensitive + whole_words）差 6 轮，P0 独有 uid4/5/9/10/11/12/13/16/25/7/21；M7_match_ablation_delta=0.166667，CI=[-0.333333,0.666667]，n=6——区间跨 0，方向未定。
- M8 代价：单档端到端 p50 为 573–596 毫秒（同一批 runner 采样，进程启动计入），基线同口径 p50 为 42–72 毫秒；依赖 25 个包、`.venv` 64.5 MiB、源码快照 24.9 MiB；安装 4 秒下载 + 5 秒建 venv + 52 秒 pip；运行期零网络、零凭据。

## 1. 被测对象与版本

| 项 | 值 |
| --- | --- |
| 仓库 | https://github.com/diceframe/diceframe |
| commit sha | `d2246e0d0d32867e8e090c238b588441bad96a28` |
| commit 时间 | 2026-10-14T05:46:36Z |
| 引擎版本 | `src/version.py` 的 `__version__ = "2.6.1"`（写入 out 的 `adapter_version`） |
| 快照来源 | codeload 压缩包（不用 git clone），`adapters/diceframe/fetch_upstream.sh` 按 sha 重建 |
| 压缩包 sha256 | `beaa511e409676e00a1db43d4b5fb360aea908b9d692529d2d2f6d9060b16d04` |
| 适配器 | `bench/roleplay_eval/adapters/diceframe/run.py`，字段映射与缺口见同目录 README.md |
| 运行环境 | Python 3.13.13 + venv（25 个包），Windows 11 + MSYS2/Git-Bash |
| 输入夹具 | `bench/roleplay_eval/data/worldbook.json`（25 条）、`chat.jsonl`（12 条）、`profiles.json`（P0–P4） |

out JSON 的 `engine_env` 字段：`python=3.13.13`、`entry=bench/roleplay_eval/adapters/diceframe/run.py`、`upstream=bench/roleplay_eval/adapters/diceframe/upstream`、`llm=none`、`network=none`；`upstream_commit` 取上表 sha。

## 2. 复现步骤

以下命令第三方可原样粘贴（从仓库根执行）。第 4–7 步用第 2 步建好的 venv python：runner 用 `sys.executable` 启动适配器，因此必须用带 diceframe 依赖的解释器跑 runner。

```
# 1. 取被测源码（锁定 sha；codeload，不用 git clone）
cd bench/roleplay_eval/adapters/diceframe
bash fetch_upstream.sh

# 2. 建 venv 并装依赖（Tsinghua 镜像；运行期不需要网络与凭据）
bash setup.sh
cd ../../../..

# 3. 直接跑适配器单档（产出契约 JSON ＋ stdout 读数行）
python -X utf8 bench/roleplay_eval/adapters/diceframe/run.py --data bench/roleplay_eval/data --profile P0 --out bench/roleplay_eval/out/diceframe_P0.json

# 4. 五档读数：写 out/diceframe_P*.json、raw/diceframe_P*.txt、raw/diceframe_P*.json、raw/diceframe_summary.json
./bench/roleplay_eval/adapters/diceframe/.venv/Scripts/python.exe -X utf8 bench/roleplay_eval/harness/runner.py --adapter diceframe --profiles P0,P1,P2,P3,P4

# 5. 逐档契约校验（退出码 0 才算通过；--strict-content 追加「块正文与夹具逐字一致」判据）
for p in P0 P1 P2 P3 P4; do ./bench/roleplay_eval/adapters/diceframe/.venv/Scripts/python.exe -X utf8 bench/roleplay_eval/harness/validate.py bench/roleplay_eval/out/diceframe_$p.json --data bench/roleplay_eval/data --strict-content; done

# 6. 差异与 KPI：写 raw/diceframe_baseline_diff.txt、raw/diceframe_diff.txt、raw/diceframe_kpi.txt，并补 raw/diceframe_summary.json 的 kpi 字段
./bench/roleplay_eval/adapters/diceframe/.venv/Scripts/python.exe -X utf8 bench/roleplay_eval/harness/score.py --name diceframe

# 7. 确定性：每档连跑 5 次比 sha256，写 raw/diceframe_determinism.txt
./bench/roleplay_eval/adapters/diceframe/.venv/Scripts/python.exe -X utf8 bench/roleplay_eval/adapters/diceframe/verify_determinism.py --repeats 5
```

期望结果：第 5 步五档均为 `checks=60 fail=0`、退出码 0（完整 stdout 见 `raw/diceframe_validate.txt`，逐档 `SUMMARY` 行后跟 `rc=0`）；第 6 步末行给出 `missing_profiles=0`；第 7 步末行为 `SUMMARY adapter=diceframe repeats=5 failures=0`。

run.py 的 `--upstream` 缺省指向 `adapters/diceframe/upstream`，也可用环境变量 `DICEFRAME_UPSTREAM` 覆盖；适配器只读 `--data`、只写 `--out`，不读工作目录以外的用户数据。

## 3. 基线 vs 方案对照读数

激活条数（turn1..turn6，来自 `out/diceframe_P*.json` 与 `raw/diceframe_summary.json`、`raw/baseline_summary.json`）：

| 档位 | diceframe | baseline |
| --- | --- | --- |
| P0 | 8/14/9/6/5/4 | 8/13/8/7/5/4 |
| P1 | 8/13/8/6/5/4 | 8/12/7/7/5/4 |
| P2 | 2/3/3/4/3/3 | 2/4/4/5/3/3 |
| P3 | 7/13/8/5/4/3 | 7/12/7/6/4/3 |
| P4 | 7/7/2/2/2/2 | 7/7/2/2/2/2 |

P0 逐轮差异（方案 vs 基线，逐字取自 `raw/diceframe_baseline_diff.txt`）：

```
DIFF diceframe baseline P0 turn=1 only_a=- only_b=- same=8
DIFF diceframe baseline P0 turn=2 only_a=9 only_b=- same=13
DIFF diceframe baseline P0 turn=3 only_a=9,16 only_b=15 same=7
DIFF diceframe baseline P0 turn=4 only_a=16 only_b=10,15 same=5
DIFF diceframe baseline P0 turn=5 only_a=- only_b=- same=5
DIFF diceframe baseline P0 turn=6 only_a=- only_b=- same=4
```

P4 逐轮差异（匹配口径档位上两家完全一致）：

```
DIFF diceframe baseline P4 turn=1 only_a=- only_b=- same=7
DIFF diceframe baseline P4 turn=2 only_a=- only_b=- same=7
DIFF diceframe baseline P4 turn=3 only_a=- only_b=- same=2
DIFF diceframe baseline P4 turn=4 only_a=- only_b=- same=2
DIFF diceframe baseline P4 turn=5 only_a=- only_b=- same=2
DIFF diceframe baseline P4 turn=6 only_a=- only_b=- same=2
```

同方案跨档消融（逐字取自 `raw/diceframe_diff.txt`）：

```
# P0vsP3=budget（active 口径另加一行 .dropped 口径） P0vsP1=recursive P0vsP2=scan_depth P0vsP4=match_profile
DIFF diceframe@P0 diceframe@P1 P0vsP1 turn=1 only_a=- only_b=- same=8
DIFF diceframe@P0 diceframe@P1 P0vsP1 turn=2 only_a=13 only_b=- same=13
DIFF diceframe@P0 diceframe@P1 P0vsP1 turn=3 only_a=13 only_b=- same=8
DIFF diceframe@P0 diceframe@P1 P0vsP1 turn=4 only_a=- only_b=- same=6
DIFF diceframe@P0 diceframe@P1 P0vsP1 turn=5 only_a=- only_b=- same=5
DIFF diceframe@P0 diceframe@P1 P0vsP1 turn=6 only_a=- only_b=- same=4
# P0vsP3=budget（active 口径另加一行 .dropped 口径） P0vsP1=recursive P0vsP2=scan_depth P0vsP4=match_profile
DIFF diceframe@P0 diceframe@P3 P0vsP3 turn=1 only_a=20 only_b=- same=7
DIFF diceframe@P0.dropped diceframe@P3.dropped P0vsP3 turn=1 only_a=- only_b=20 same=0
DIFF diceframe@P0 diceframe@P3 P0vsP3 turn=2 only_a=20 only_b=- same=13
DIFF diceframe@P0.dropped diceframe@P3.dropped P0vsP3 turn=2 only_a=- only_b=20 same=0
DIFF diceframe@P0 diceframe@P3 P0vsP3 turn=3 only_a=20 only_b=- same=8
DIFF diceframe@P0.dropped diceframe@P3.dropped P0vsP3 turn=3 only_a=- only_b=20 same=0
DIFF diceframe@P0 diceframe@P3 P0vsP3 turn=4 only_a=20 only_b=- same=5
DIFF diceframe@P0.dropped diceframe@P3.dropped P0vsP3 turn=4 only_a=- only_b=20 same=0
DIFF diceframe@P0 diceframe@P3 P0vsP3 turn=5 only_a=20 only_b=- same=4
DIFF diceframe@P0.dropped diceframe@P3.dropped P0vsP3 turn=5 only_a=- only_b=20 same=0
DIFF diceframe@P0 diceframe@P3 P0vsP3 turn=6 only_a=20 only_b=- same=3
DIFF diceframe@P0.dropped diceframe@P3.dropped P0vsP3 turn=6 only_a=- only_b=20 same=0
# P0vsP3=budget（active 口径另加一行 .dropped 口径） P0vsP1=recursive P0vsP2=scan_depth P0vsP4=match_profile
DIFF diceframe@P0 diceframe@P2 P0vsP2 turn=1 only_a=2,3,4,6,18,19 only_b=- same=2
DIFF diceframe@P0 diceframe@P2 P0vsP2 turn=2 only_a=2,3,4,5,6,9,10,12,13,18,19 only_b=- same=3
DIFF diceframe@P0 diceframe@P2 P0vsP2 turn=3 only_a=9,10,11,12,13,16 only_b=- same=3
DIFF diceframe@P0 diceframe@P2 P0vsP2 turn=4 only_a=16,25 only_b=- same=4
DIFF diceframe@P0 diceframe@P2 P0vsP2 turn=5 only_a=13,14 only_b=- same=3
DIFF diceframe@P0 diceframe@P2 P0vsP2 turn=6 only_a=21 only_b=- same=3
# P0vsP3=budget（active 口径另加一行 .dropped 口径） P0vsP1=recursive P0vsP2=scan_depth P0vsP4=match_profile
DIFF diceframe@P0 diceframe@P4 P0vsP4 turn=1 only_a=4 only_b=- same=7
DIFF diceframe@P0 diceframe@P4 P0vsP4 turn=2 only_a=4,5,9,10,11,12,13 only_b=- same=7
DIFF diceframe@P0 diceframe@P4 P0vsP4 turn=3 only_a=9,10,11,12,13,16,25 only_b=- same=2
DIFF diceframe@P0 diceframe@P4 P0vsP4 turn=4 only_a=13,14,16,25 only_b=- same=2
DIFF diceframe@P0 diceframe@P4 P0vsP4 turn=5 only_a=13,14,21 only_b=- same=2
DIFF diceframe@P0 diceframe@P4 P0vsP4 turn=6 only_a=7,21 only_b=- same=2
```

KPI（逐字取自 `raw/diceframe_kpi.txt`）：

```
KPI M1_active_f1 value=0.925954 ci=[0.846154,0.993827] n=6
KPI M1_active_f1_delta value=-0.0740461 ci=[-0.153846,-0.00617284] n=6
KPI M1_active_symdiff value=1.16667 ci=[0.166667,2.33333] n=6
KPI M2_order_inv value=11.3333 ci=[3.16667,23.5] n=6
KPI M2_order_inv_delta value=8.5 ci=[2.83333,17.5] n=6
KPI M3_budget_dropped_delta value=0 ci=[0,0] n=6
KPI M4_recursion_ablation_delta value=0 ci=[0,0] n=6
KPI M5_depth_ablation_delta value=0.666667 ci=[0,1.33333] n=6
KPI M6_determinism value=1 ci=[1,1] n=5
KPI M7_match_ablation_delta value=0.166667 ci=[-0.333333,0.666667] n=6
KPI M8_total_active_uids value=170 ci=[135,206] n=30
```

四条差异的成因，逐条给引擎依据：

1. uid9/uid10（条目级 `depth`）：引擎的 ST 适配器把 `depth` 列进不建模字段（`upstream/src/lorebook/adapters/sillytavern.py:21-28`），导入后只留在 `extensions`；因此两条都按档位窗口判定。基线按 §2 规则 1 用条目 `depth` 覆盖窗口，于是 turn2 基线不激活 uid9，而方案激活。
2. uid15/uid16（`group_weight`）：引擎的 `_weighted_pick` 按权重做一次随机抽取（`upstream/src/lorebook/matcher.py:721-734`），种子固定后结果可复现；seed=20261014 时抽中 uid16，基线按「取最大权重」选 uid15。
3. uid20（超长常驻，P3）：引擎 `apply_token_budget` 在 `used + cost > budget` 时跳过该条并记 omitted（`upstream/src/lorebook/budget.py:69-80`），与基线的「跳过不截断」同结果。
4. 注入顺序：引擎最终顺序由 `_merge_and_sort` 的 `tier → order 升序 → 来源 → 语义分 → id 字符串序` 决定（`upstream/src/lorebook/retrieval.py:610-636`）；基线按 §2 规则 9 的 `order` 降序。两者方向相反，故 M2 逆序对数偏大。

## 4. 读数明细

### 4.1 能力与缺口行

```
CAPS diceframe {"at_depth":false,"group":true,"probability":true,"recursive":true,"regex_key":true,"whole_words_cjk":"no_match_cjk"}
UNSUPPORTED diceframe field=depth reason=st-depth-in-engine-unmapped-fields
UNSUPPORTED diceframe field=position reason=st-position-anchor-no-canonical-prompt-slot
UNSUPPORTED diceframe field=capability_probe reason=fixture-marker-not-an-engine-field
UNSUPPORTED diceframe field=macro_expand reason=engine-src-has-no-macro-expander
```

`whole_words_cjk=no_match_cjk` 的实测依据：uid8 的键「雨」在条目级 `match_whole_words=true`，引擎实现为 `(?<!\w)…(?!\w)`，Python 的 `\w` 覆盖 CJK 字符，于是「下雨」「雨伞」都不算命中；uid8 在 P0–P4 五档六轮全部未激活（对照 `raw/diceframe_P0.txt` 各轮 `order` 列表）。

`regex_key=true` 的依据是源码路径：键写成 `/…/` 时引擎按 Python 正则执行（`upstream/src/lorebook/matcher.py:498-510`），正则不可编译时返回未命中而不抛错。uid24 的键 `/地.图/` 在 12 条对话里没有「地?图」形态文本（夹具在 i=4 只有「地图」），因此该探针六轮都未激活；正则通道与字面通道在本题上没有产生可区分的激活差。

### 4.2 五档 READOUT 行

P0（逐字取自 `raw/diceframe_P0.txt`）：

```
READOUT diceframe P0 turn=1 active=8 order=19,4,3,1,2,6,20,18 chars=1107 bytes=3297 dropped=-
READOUT diceframe P0 turn=2 active=14 order=19,9,13,10,4,3,11,12,1,2,6,5,20,18 chars=1253 bytes=3735 dropped=-
READOUT diceframe P0 turn=3 active=9 order=9,13,10,11,12,1,16,25,20 chars=1140 bytes=3376 dropped=-
READOUT diceframe P0 turn=4 active=6 order=13,1,14,16,25,20 chars=1070 bytes=3166 dropped=-
READOUT diceframe P0 turn=5 active=5 order=13,1,21,14,20 chars=1034 bytes=3102 dropped=-
READOUT diceframe P0 turn=6 active=4 order=1,21,7,20 chars=1009 bytes=3027 dropped=-
```

P1：

```
READOUT diceframe P1 turn=1 active=8 order=19,4,3,1,2,6,20,18 chars=1107 bytes=3297 dropped=-
READOUT diceframe P1 turn=2 active=13 order=19,9,10,4,3,11,12,1,2,6,5,20,18 chars=1225 bytes=3651 dropped=-
READOUT diceframe P1 turn=3 active=8 order=9,10,11,12,1,16,25,20 chars=1112 bytes=3292 dropped=-
READOUT diceframe P1 turn=4 active=6 order=13,1,14,16,25,20 chars=1070 bytes=3166 dropped=-
READOUT diceframe P1 turn=5 active=5 order=13,1,21,14,20 chars=1034 bytes=3102 dropped=-
READOUT diceframe P1 turn=6 active=4 order=1,21,7,20 chars=1009 bytes=3027 dropped=-
```

P2：

```
READOUT diceframe P2 turn=1 active=2 order=1,20 chars=956 bytes=2868 dropped=-
READOUT diceframe P2 turn=2 active=3 order=11,1,20 chars=981 bytes=2943 dropped=-
READOUT diceframe P2 turn=3 active=3 order=1,25,20 chars=995 bytes=2941 dropped=-
READOUT diceframe P2 turn=4 active=4 order=13,1,14,20 chars=1010 bytes=3030 dropped=-
READOUT diceframe P2 turn=5 active=3 order=1,21,20 chars=980 bytes=2940 dropped=-
READOUT diceframe P2 turn=6 active=3 order=1,7,20 chars=985 bytes=2955 dropped=-
```

P3：

```
READOUT diceframe P3 turn=1 active=7 order=19,4,3,1,2,6,18 chars=207 bytes=597 dropped=20
READOUT diceframe P3 turn=2 active=13 order=19,9,13,10,4,3,11,12,1,2,6,5,18 chars=353 bytes=1035 dropped=20
READOUT diceframe P3 turn=3 active=8 order=9,13,10,11,12,1,16,25 chars=240 bytes=676 dropped=20
READOUT diceframe P3 turn=4 active=5 order=13,1,14,16,25 chars=170 bytes=466 dropped=20
READOUT diceframe P3 turn=5 active=4 order=13,1,21,14 chars=134 bytes=402 dropped=20
READOUT diceframe P3 turn=6 active=3 order=1,21,7 chars=109 bytes=327 dropped=20
```

P4：

```
READOUT diceframe P4 turn=1 active=7 order=19,3,1,2,6,20,18 chars=1081 bytes=3219 dropped=-
READOUT diceframe P4 turn=2 active=7 order=19,3,1,2,6,20,18 chars=1081 bytes=3219 dropped=-
READOUT diceframe P4 turn=3 active=2 order=1,20 chars=956 bytes=2868 dropped=-
READOUT diceframe P4 turn=4 active=2 order=1,20 chars=956 bytes=2868 dropped=-
READOUT diceframe P4 turn=5 active=2 order=1,20 chars=956 bytes=2868 dropped=-
READOUT diceframe P4 turn=6 active=2 order=1,20 chars=956 bytes=2868 dropped=-
```

### 4.3 确定性

每档连跑 5 次的 stdout sha256 与 out JSON sha256（out JSON 的 5 次 SHA 行相同，这里各取一行；完整 5 次见 `raw/diceframe_determinism.txt`）：

```
SHA 83f0bc564b5d16cc4c5dad50d6aada7c6660e617f31ca64341493ec1c0de4715 file=out/diceframe_P0.json
SHA 12956901b3c5e7007dbaeb82a661e8911eac7f15b9fb6895dc49ec58bc5544fd file=out/diceframe_P1.json
SHA 942b83cdbfb5161fc80dd4f91b3e38921532e3c9cb33b8b0c8de4dc65fda20f4 file=out/diceframe_P2.json
SHA f0d58f0c5591976ddd7d9e0a4a538f8ee64f279160cc6fe1b3a4ad38694b59fd file=out/diceframe_P3.json
SHA 882518585bbdc716c4c60164e603ddc26597675da1ed6345ac9c114a2b319293 file=out/diceframe_P4.json
DETERMINISM diceframe repeats=5 identical=true sha=e983df23c1dbb66169a06a13778131c4d11fcd80bbaf548a9629165094595507
DETERMINISM diceframe repeats=5 identical=true sha=025a18b329ae728b87674c3c3e54e024f43d3a091d0cd99505916419fd0e3f5b
DETERMINISM diceframe repeats=5 identical=true sha=9ece59bbd8106fef04360995f7628829f6207cd673d58ada819be54bc66fbcd9
DETERMINISM diceframe repeats=5 identical=true sha=78726efb884811b3ab61dd5b9b34dd9846d29c90496f459c8742cfb3455ffc1d
DETERMINISM diceframe repeats=5 identical=true sha=01094e144f06654f012cfb3eedc07f8e1311e4f86b7afdb0ad7345e0b1db9bc7
```

runner 另外做了 1 次预热 + 8 次采样，8 次 stdout 摘要全等，与上面的 5 次结论同值（见 `raw/diceframe_repeat.txt`、`raw/diceframe_runner.txt`）。确定性来源：概率门与组内加权随机共用一个按 `seed=20261014` 每轮重置的 rng；条目 id 由 `import_entry_id` 从 uid 派生；排序键最后一级用唯一 id 收尾。

### 4.4 耗时

diceframe 五档（预热 1 次 + 采样 7 次；一次采样＝启动适配器进程并跑完 6 个 turn 的墙钟时间）：

```
TIMING diceframe profile=P0 min_ms=569.313 p50_ms=591.446 p95_ms=630.937
TIMING diceframe profile=P1 min_ms=566.467 p50_ms=585.316 p95_ms=609.859
TIMING diceframe profile=P2 min_ms=566.021 p50_ms=578.185 p95_ms=619.697
TIMING diceframe profile=P3 min_ms=579.445 p50_ms=595.724 p95_ms=619.64
TIMING diceframe profile=P4 min_ms=567.737 p50_ms=573.173 p95_ms=578.964
```

基线同口径（取自 `raw/baseline_runner.txt`，为同机较早一次运行）：

```
TIMING baseline profile=P0 min_ms=44.4012 p50_ms=46.2834 p95_ms=66.0251
TIMING baseline profile=P1 min_ms=50.2471 p50_ms=72.3784 p95_ms=96.7965
TIMING baseline profile=P2 min_ms=44.2366 p50_ms=46.6111 p95_ms=69.4322
TIMING baseline profile=P3 min_ms=41.4117 p50_ms=42.3216 p95_ms=44.7103
TIMING baseline profile=P4 min_ms=42.7917 p50_ms=43.2326 p95_ms=44.8852
```

两批采样不在同一次运行，机器负载不同（采样期间同机还有其它任务），因此这组数字只作量级对照：diceframe 单档 p50 约 0.57–0.60 秒，基线约 0.042–0.072 秒。差值主要来自导入 `src.lorebook.retrieval` 一链（含 engine / memory / webui 依赖）的解释器启动成本，进程启动计入采样。

### 4.5 依赖体积与安装耗时（本机实测）

| 项 | 实测值 |
| --- | --- |
| codeload 下载 + 解压 | 4 秒 |
| `python -m venv` | 5 秒 |
| `pip install`（Tsinghua 镜像，25 个包） | 52 秒 |
| `.venv` | 66001 KB（≈ 64.5 MiB） |
| `upstream/` 源码快照 | 25495 KB（≈ 24.9 MiB） |
| 直接依赖 | aiohttp、cryptography、edge-tts、Pillow、peewee ＋ 测试用 pytest、pytest-asyncio |
| 凭据 | 运行期零凭据：夹具、适配器、读数链路都不读 API key，不发网络请求 |

### 4.6 契约校验

五档 `harness/validate.py --strict-content` 全部退出码 0：逐档 `checks=60 fail=0`，共 300 个 OK、0 个 FAIL；其中 C10-block-content 逐块与夹具正文的字符数、字节数、sha256 全部对上（完整 stdout 见 `raw/diceframe_validate.txt`）。

## 5. 不适用条件

本报告的读数只覆盖确定性、无 LLM 的世界书激活与字符预算面：同一批 25 条夹具条目、同一份 12 条对话、五个档位、六个评估轮。凡依赖向量检索、模型生成、外部服务或人工判断的场景都不在这套夹具的适用范围内；引擎的可见性（`visible_to`）、计时器（`sticky` / `cooldown` / `delay`）、多 Book 绑定与 SQLite 持久化、WebUI 与插件宿主也未进入本次工作负载。读到「激活条数多/少」时只能按本夹具的 25 条条目与 12 条对话解释，不能外推到其它世界书规模。

## 6. 未测项与原因

1. embedding 语义检索通道：未测。原因：该通道需要 embedding 服务；引擎在拿不到客户端时直接返回空候选（`upstream/src/lorebook/retrieval.py:695-697`），本任务禁止网络与凭据，故适配器传 `extra_candidates=None`，本轮读数不含语义候选。
2. 真实 LLM 生成：未测。原因：任务硬禁 LLM 调用与凭据；叙事生成、世界生成、规则生成三条链路都不在本次读数内。
3. TTS / ASR / 图像面：未测。原因：三条链路都要外部服务或本地模型（`upstream/src/tts/providers.py`、`upstream/src/asr/providers.py`、`upstream/src/imagegen/providers.py`），与本次世界书激活面无关。
4. `unsupported` 字段逐条未测：
   - `depth`：未测。原因：引擎不建模 ST 的 `depth`（`upstream/src/lorebook/adapters/sillytavern.py:21-28`），条目级扫描窗口在引擎里没有对应字段，uid9（depth=1）与 uid10（depth=6）都按档位窗口判定，读数 `blocks[].depth` 是夹具请求值的回填。
   - `position`：未测。原因：引擎只接受 5 个 canonical slot 名做 `prompt_slot`（`upstream/src/lorebook/adapters/sillytavern.py:12-17,107-114`），`before_char` / `after_char` / `at_depth` 一律落空；注入位置没有引擎读数，读数 `blocks[].position` 是夹具请求值的回填。
   - `capability_probe`：未测。原因：这是夹具标记，引擎无对应字段；它不影响激活，只用于标注 uid24 与 uid25 两条探针。
   - `macro_expand`：未测。原因：`src/` 全库检索 `macro` 零命中，世界书正文里的 `{{roll:d6}}` 与 `{{user}}` 原样保留，引擎不做内容宏替换；uid25 的正文按字面串参与字符计数与递归扫描。
5. 其他未测项：引擎自带全量测试套件（本次只跑适配器链路）；SQLite 持久化与多 Book 绑定；`sticky` / `cooldown` / `delay` 计时器行为（夹具无这三个字段）；`visible_to` 视角过滤（本次以无视角限制的调用形态测）；fuzzy 回退开启后的读数（按引擎对 ST 导入书的默认值置为关）；非 Windows 平台与 Python 3.12（CI 版本）上的读数。

