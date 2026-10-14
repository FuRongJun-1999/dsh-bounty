# SillyTavern v0.1 · 角色扮演横评交付报告

方向：角色扮演（世界书触发 ＋ 上下文预算）。判据文件：`bench/roleplay_eval/harness/CONTRACT.md`（冻结契约 v1）。
本报告围栏里的每一行都取自 `bench/roleplay_eval/raw/` 下的文件，可逐字回查。

## 0. 结论摘要

1. **激活面与基线基本重合**：P0 六个 turn 里 turn4／turn5／turn6 的激活集与基线逐条相同，turn1／turn2／turn3 只差 uid8 一条（M1，`raw/sillytavern_baseline_diff.txt`）。
2. **注入顺序与基线差距大**：同一激活集上方案侧逆序对数均值 22.6667，Δ +19.8333（M2，`raw/sillytavern_kpi.txt`）。
3. **预算口径不同，不可直接比字符数**：ST 的预算是 token，等于 `maxContext` 的 25%；P0 取不构成约束的 `maxContext=16384`（token 预算 4096），P3 取 2458（token 预算 615）。P3 与基线可比的只有 dropped 条目集合（M3，`raw/sillytavern_timing.txt`）。
4. **紧预算下方案丢得比基线多**：P0 与 P3 的 dropped 集合差 Δ +1.3333；方案侧 P0 一个都不丢，P3 每 turn 丢 2–3 条（M3，`raw/sillytavern_kpi.txt` 与 `raw/sillytavern_diff.txt`）。
5. **递归消融幅度与基线一致**：关掉递归后方案只丢 uid13，Δ 0（M4，`raw/sillytavern_kpi.txt`）。
6. **深度消融**：`scan_depth` 由 4 降到 1 后方案激活集缩小，Δ +0.5（M5，`raw/sillytavern_kpi.txt`）。
7. **匹配口径消融方向相反**：P4 下方案少丢条目，Δ −3.3333；原因是 ST 的全词边界把 CJK 当非词字符，uid8 仍命中（M7，`raw/sillytavern_kpi.txt`）。
8. **确定性成立**：同输入 5 次独立进程，stdout 与 out JSON 的 sha256 逐次一致，5/5 `identical=true`（M6，`raw/sillytavern_determinism.txt`）。
9. **代价**：`npm ci` 9 s（829 包），`node_modules` 337,045,122 字节，冷起服务 3,336 ms，单档端到端 p50 3,707 ms；运行期零凭据，不请求任何模型 API（M8，`raw/sillytavern_runner.txt`）。

## 1. 被测对象与版本

| 项 | 值 |
| --- | --- |
| 仓库 | https://github.com/SillyTavern/SillyTavern |
| commit | `06bde939fb1e9c4c8d8641d810f0a916b5bce127`（release 分支，2026-09-14） |
| 引擎版本 | `package.json` 的 `1.19.0` |
| 适配器 | `bench/roleplay_eval/adapters/sillytavern/`，脚本版本 `st-roleplay-eval-adapter/0.1` |
| 读数入口 | `public/scripts/world-info.js` 的 `checkWorldInfo(chat, maxContext, isDryRun=true)`（`:4709`） |
| 快照校验 | codeload 压缩包 38,087,675 字节，sha256 `d3c5b32e7a1b649366d7d35eaaf877b06376864aacd8713ee8e670ff8ee4099c`；解出 1010 文件；`fetch_upstream.sh` 校验 `package.json` 的 version |

适配器不改上游源码：只把世界书写进它自己的用户目录 `upstream/data/default-user/worlds/`，两个文件每次运行重建（`roleplay_eval.json` 为当前档位映射，`roleplay_eval_p0.json` 为 P0 映射，供锚点搜索用）。

## 2. 复现步骤

第三方从零复跑（Windows ＋ MSYS2/Git-Bash；node v24.16.0、npm 11.13.0）：

```bash
# 1) 取源码快照（按锁定 sha，走 codeload）——下载实测 7 s，38,087,675 字节
cd bench/roleplay_eval/adapters/sillytavern
bash fetch_upstream.sh

# 2) 装依赖——npm ci 实测 9 s（缓存已热）；tests 依赖 npm install 依赖已就位时 1 s
export CHROME_PATH="C:/Users/Zs/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe"
bash setup.sh

# 3) 起本地 ST 服务（run.mjs 也会按需自起；这一步只为把冷起耗时从读数里分出来）——冷起实测 3.3 s
cd upstream && node server.js --port 8123 &
cd ../../../..

# 4) 跑五档读数——每档 8 次（1 次预热 ＋ 7 次采样），单次约 3.5–4.2 s，五档合计约 2.5 min
python -X utf8 bench/roleplay_eval/harness/runner.py --adapter sillytavern --profiles P0,P1,P2,P3,P4

# 5) 逐档校验契约 §3.2——五档各 58–60 项检查，全部 fail=0
for p in P0 P1 P2 P3 P4; do python -X utf8 bench/roleplay_eval/harness/validate.py bench/roleplay_eval/out/sillytavern_$p.json; done

# 6) 出 DIFF／KPI——约 1 s
python -X utf8 bench/roleplay_eval/harness/score.py --name sillytavern

# 7) 确定性核验（5 次独立进程 × 5 档）——约 100 s
node bench/roleplay_eval/adapters/sillytavern/verify_determinism.mjs --repeats 5
```

单档最小复跑：

```bash
node bench/roleplay_eval/adapters/sillytavern/run.mjs \
  --data bench/roleplay_eval/data --profile P0 --out bench/roleplay_eval/out/sillytavern_P0.json
```

预期耗时（本机实测）：取源码 7 s（下载）＋ 解压数秒；依赖安装 10 s（缓存已热）；冷起服务 3.3 s；单档端到端 3.5–8.7 s（是否含冷起决定上下界）；五档 runner 约 2.5 min；五档校验 1 s；评分 1 s；确定性核验约 100 s。

## 3. 基线 vs 方案对照读数

方案与基线在同一份夹具、同一档位下逐 turn 对照（M1／M2／M3）。P0：

```
CAPS sillytavern {"at_depth":true,"group":true,"probability":true,"recursive":true,"regex_key":true,"whole_words_cjk":"cjk-treated-as-boundary"}
READOUT sillytavern P0 turn=1 active=9 order=19,20,8,3,2,1,18,6,4 chars=1137 bytes=3387 dropped=-
READOUT sillytavern P0 turn=2 active=14 order=19,13,20,12,11,8,3,2,1,18,10,6,5,4 chars=1260 bytes=3756 dropped=-
READOUT sillytavern P0 turn=3 active=9 order=13,25,20,15,12,11,8,1,10 chars=1131 bytes=3377 dropped=-
READOUT sillytavern P0 turn=4 active=7 order=25,20,15,14,13,1,10 chars=1075 bytes=3209 dropped=-
READOUT sillytavern P0 turn=5 active=5 order=21,20,14,13,1 chars=1034 bytes=3102 dropped=-
READOUT sillytavern P0 turn=6 active=4 order=21,20,7,1 chars=1009 bytes=3027 dropped=-
UNSUPPORTED sillytavern field=group_weight reason=st-group-winner-is-weighted-random-not-max-weight
UNSUPPORTED sillytavern field=recursion.delay reason=contract-defines-no-delay-rule-and-st-semantics-differs
UNSUPPORTED sillytavern field=capability_probe reason=fixture-marker-not-an-engine-field
UNSUPPORTED sillytavern field=budget_chars reason=st-budget-is-token-share-of-max-context-not-chars
UNSUPPORTED sillytavern field=whole_words_cjk reason=st-whole-word-boundary-treats-cjk-as-non-word-char
ENGINE_NOTE sillytavern profile=P0 max_context=16384 budget_tokens=4096 anchor_max_context=16384 budget_delta_vs_p0=0
ENGINE_NOTE sillytavern anchor_probe=256:binding,512:binding,1024:binding,2048:binding,4096:binding,8192:binding,16384:non-binding
```

基线 P0 同档：

```
READOUT baseline P0 turn=1 active=8 order=18,1,2,3,4,6,20,19 chars=1107 bytes=3297 dropped=-
READOUT baseline P0 turn=2 active=13 order=18,1,2,3,4,5,6,10,11,12,13,20,19 chars=1230 bytes=3666 dropped=-
READOUT baseline P0 turn=3 active=8 order=1,10,11,12,13,15,20,25 chars=1115 bytes=3301 dropped=-
READOUT baseline P0 turn=4 active=7 order=1,10,13,14,15,20,25 chars=1089 bytes=3223 dropped=-
READOUT baseline P0 turn=5 active=5 order=1,13,14,20,21 chars=1034 bytes=3102 dropped=-
READOUT baseline P0 turn=6 active=4 order=1,7,20,21 chars=1009 bytes=3027 dropped=-
```

逐 turn 差异（`only_a`＝方案独有，`only_b`＝基线独有）：

```
DIFF sillytavern baseline P0 turn=1 only_a=8 only_b=- same=8
DIFF sillytavern baseline P0 turn=2 only_a=8 only_b=- same=13
DIFF sillytavern baseline P0 turn=3 only_a=8 only_b=- same=8
DIFF sillytavern baseline P0 turn=4 only_a=- only_b=- same=7
DIFF sillytavern baseline P0 turn=5 only_a=- only_b=- same=5
DIFF sillytavern baseline P0 turn=6 only_a=- only_b=- same=4
```

P3 紧预算档的差异：

```
DIFF sillytavern baseline P3 turn=1 only_a=8 only_b=19 same=6
DIFF sillytavern baseline P3 turn=2 only_a=8 only_b=13,19 same=10
DIFF sillytavern baseline P3 turn=3 only_a=8 only_b=13,25 same=5
DIFF sillytavern baseline P3 turn=4 only_a=- only_b=25 same=5
DIFF sillytavern baseline P3 turn=5 only_a=- only_b=21 same=3
DIFF sillytavern baseline P3 turn=6 only_a=- only_b=21 same=2
```

方案 P3 与基线 P3 的读数：

```
READOUT sillytavern P3 turn=1 active=7 order=8,3,2,1,18,6,4 chars=213 bytes=627 dropped=19,20
READOUT sillytavern P3 turn=2 active=11 order=12,11,8,3,2,1,18,10,6,5,4 chars=308 bytes=912 dropped=13,19,20
READOUT sillytavern P3 turn=3 active=6 order=15,12,11,8,1,10 chars=178 bytes=534 dropped=13,20,25
READOUT sillytavern P3 turn=4 active=5 order=15,14,13,1,10 chars=150 bytes=450 dropped=20,25
READOUT sillytavern P3 turn=5 active=3 order=14,13,1 chars=110 bytes=330 dropped=20,21
READOUT sillytavern P3 turn=6 active=2 order=7,1 chars=85 bytes=255 dropped=20,21
READOUT baseline P3 turn=1 active=7 order=18,1,2,3,4,6,19 chars=207 bytes=597 dropped=20
READOUT baseline P3 turn=2 active=12 order=18,1,2,3,4,5,6,10,11,12,13,19 chars=330 bytes=966 dropped=20
READOUT baseline P3 turn=3 active=7 order=1,10,11,12,13,15,25 chars=215 bytes=601 dropped=20
READOUT baseline P3 turn=4 active=6 order=1,10,13,14,15,25 chars=189 bytes=523 dropped=20
READOUT baseline P3 turn=5 active=4 order=1,13,14,21 chars=134 bytes=402 dropped=20
READOUT baseline P3 turn=6 active=3 order=1,7,21 chars=109 bytes=327 dropped=20
```

读法：P0 下两家只在 uid8 上分叉——ST 的单键全词用 `(?:^|\\W)(key)(?:$|\\W)`，JS 正则把 CJK 当非词字符，故「雨」在「下雨」内命中；基线的 `\\b` 语义不命中。P3 下两家的 dropped 集合不同（方案丢 uid20 等，基线只丢 uid20 之外还保住了 uid19），这正是 M3 的集合口径。

## 4. 读数明细

### 4.1 五档 READOUT（`raw/sillytavern_P0.txt` … `raw/sillytavern_P4.txt`）

```
READOUT sillytavern P1 turn=1 active=9 order=19,20,8,3,2,1,18,6,4 chars=1137 bytes=3387 dropped=-
READOUT sillytavern P1 turn=2 active=13 order=19,20,12,11,8,3,2,1,18,10,6,5,4 chars=1232 bytes=3672 dropped=-
READOUT sillytavern P1 turn=3 active=8 order=25,20,15,12,11,8,1,10 chars=1103 bytes=3293 dropped=-
READOUT sillytavern P1 turn=4 active=7 order=25,20,15,14,13,1,10 chars=1075 bytes=3209 dropped=-
READOUT sillytavern P1 turn=5 active=5 order=21,20,14,13,1 chars=1034 bytes=3102 dropped=-
READOUT sillytavern P1 turn=6 active=4 order=21,20,7,1 chars=1009 bytes=3027 dropped=-
READOUT sillytavern P2 turn=1 active=3 order=20,8,1 chars=986 bytes=2958 dropped=-
READOUT sillytavern P2 turn=2 active=4 order=20,11,1,10 chars=1002 bytes=3006 dropped=-
READOUT sillytavern P2 turn=3 active=5 order=25,20,17,1,10 chars=1028 bytes=3068 dropped=-
READOUT sillytavern P2 turn=4 active=5 order=20,14,13,1,10 chars=1031 bytes=3093 dropped=-
READOUT sillytavern P2 turn=5 active=3 order=21,20,1 chars=980 bytes=2940 dropped=-
READOUT sillytavern P2 turn=6 active=3 order=20,7,1 chars=985 bytes=2955 dropped=-
READOUT sillytavern P4 turn=1 active=9 order=19,20,8,3,2,1,18,6,4 chars=1137 bytes=3387 dropped=-
READOUT sillytavern P4 turn=2 active=13 order=19,13,20,12,8,3,2,1,18,10,6,5,4 chars=1235 bytes=3681 dropped=-
READOUT sillytavern P4 turn=3 active=8 order=13,25,20,15,12,8,1,10 chars=1106 bytes=3302 dropped=-
READOUT sillytavern P4 turn=4 active=7 order=25,20,15,14,13,1,10 chars=1075 bytes=3209 dropped=-
READOUT sillytavern P4 turn=5 active=5 order=21,20,14,13,1 chars=1034 bytes=3102 dropped=-
READOUT sillytavern P4 turn=6 active=3 order=21,20,1 chars=980 bytes=2940 dropped=-
```

### 4.2 消融 DIFF（`raw/sillytavern_diff.txt`）

```
DIFF sillytavern@P0 sillytavern@P3 P0vsP3 turn=1 only_a=19,20 only_b=- same=7
DIFF sillytavern@P0.dropped sillytavern@P3.dropped P0vsP3 turn=1 only_a=- only_b=19,20 same=0
DIFF sillytavern@P0 sillytavern@P3 P0vsP3 turn=2 only_a=13,19,20 only_b=- same=11
DIFF sillytavern@P0.dropped sillytavern@P3.dropped P0vsP3 turn=2 only_a=- only_b=13,19,20 same=0
DIFF sillytavern@P0 sillytavern@P3 P0vsP3 turn=3 only_a=13,20,25 only_b=- same=6
DIFF sillytavern@P0.dropped sillytavern@P3.dropped P0vsP3 turn=3 only_a=- only_b=13,20,25 same=0
DIFF sillytavern@P0 sillytavern@P3 P0vsP3 turn=4 only_a=20,25 only_b=- same=5
DIFF sillytavern@P0.dropped sillytavern@P3.dropped P0vsP3 turn=4 only_a=- only_b=20,25 same=0
DIFF sillytavern@P0 sillytavern@P3 P0vsP3 turn=5 only_a=20,21 only_b=- same=3
DIFF sillytavern@P0.dropped sillytavern@P3.dropped P0vsP3 turn=5 only_a=- only_b=20,21 same=0
DIFF sillytavern@P0 sillytavern@P3 P0vsP3 turn=6 only_a=20,21 only_b=- same=2
DIFF sillytavern@P0.dropped sillytavern@P3.dropped P0vsP3 turn=6 only_a=- only_b=20,21 same=0
DIFF sillytavern@P0 sillytavern@P1 P0vsP1 turn=1 only_a=- only_b=- same=9
DIFF sillytavern@P0 sillytavern@P1 P0vsP1 turn=2 only_a=13 only_b=- same=13
DIFF sillytavern@P0 sillytavern@P1 P0vsP1 turn=3 only_a=13 only_b=- same=8
DIFF sillytavern@P0 sillytavern@P1 P0vsP1 turn=4 only_a=- only_b=- same=7
DIFF sillytavern@P0 sillytavern@P1 P0vsP1 turn=5 only_a=- only_b=- same=5
DIFF sillytavern@P0 sillytavern@P1 P0vsP1 turn=6 only_a=- only_b=- same=4
DIFF sillytavern@P0 sillytavern@P2 P0vsP2 turn=1 only_a=2,3,4,6,18,19 only_b=- same=3
DIFF sillytavern@P0 sillytavern@P2 P0vsP2 turn=2 only_a=2,3,4,5,6,8,12,13,18,19 only_b=- same=4
DIFF sillytavern@P0 sillytavern@P2 P0vsP2 turn=3 only_a=8,11,12,13,15 only_b=17 same=4
DIFF sillytavern@P0 sillytavern@P2 P0vsP2 turn=4 only_a=15,25 only_b=- same=5
DIFF sillytavern@P0 sillytavern@P2 P0vsP2 turn=5 only_a=13,14 only_b=- same=3
DIFF sillytavern@P0 sillytavern@P2 P0vsP2 turn=6 only_a=21 only_b=- same=3
DIFF sillytavern@P0 sillytavern@P4 P0vsP4 turn=1 only_a=- only_b=- same=9
DIFF sillytavern@P0 sillytavern@P4 P0vsP4 turn=2 only_a=11 only_b=- same=13
DIFF sillytavern@P0 sillytavern@P4 P0vsP4 turn=3 only_a=11 only_b=- same=8
DIFF sillytavern@P0 sillytavern@P4 P0vsP4 turn=4 only_a=- only_b=- same=7
DIFF sillytavern@P0 sillytavern@P4 P0vsP4 turn=5 only_a=- only_b=- same=5
DIFF sillytavern@P0 sillytavern@P4 P0vsP4 turn=6 only_a=7 only_b=- same=3
```

P0vsP1（递归）：turn2／turn3 各丢 uid13，其余 turn 相同。P0vsP2（深度）：turn1 少 6 条、turn2 少 10 条，turn3 多出 uid17（浅扫下概率条目判过）。P0vsP3（预算）：`only_b` 侧即被预算裁掉的条目，turn1 为 uid19,20，turn3 为 uid13,20,25。P0vsP4（匹配口径）：丢 uid11 与 uid7，uid8 保留。

### 4.3 KPI（`raw/sillytavern_kpi.txt`，Δ 行＝方案 − 基线）

```
KPI M1_active_f1 value=0.974219 ci=[0.95098,0.993827] n=6
KPI M1_active_f1_delta value=-0.0257807 ci=[-0.0490196,-0.00617284] n=6
KPI M1_active_symdiff value=0.5 ci=[0.166667,0.833333] n=6
KPI M2_order_inv value=22.6667 ci=[11.6667,38.3333] n=6
KPI M2_order_inv_delta value=19.8333 ci=[10.6667,32.1667] n=6
KPI M3_budget_dropped_delta value=1.33333 ci=[1,1.66667] n=6
KPI M4_recursion_ablation_delta value=0 ci=[0,0] n=6
KPI M5_depth_ablation_delta value=0.5 ci=[0,1.16667] n=6
KPI M6_determinism value=1 ci=[1,1] n=5
KPI M7_match_ablation_delta value=-3.33333 ci=[-4.66667,-2] n=6
KPI M8_total_active_uids value=196 ci=[163,232] n=30
```

### 4.4 确定性（`raw/sillytavern_determinism.txt`）

```
DETERMINISM sillytavern repeats=5 identical=true sha=4bedb7143038ef1e332328cb0b172d20cf9577aa170e46941593a5d655cd6358
DETERMINISM sillytavern repeats=5 identical=true sha=8bd2acdc5b88a7e5540810e0e287cf0bd720ace991f41d38ab02e690f7dc43ab
DETERMINISM sillytavern repeats=5 identical=true sha=f84d8deb4873df3b7bbc4c12fb89a90be03b3095798dc0ad564ebfc5923de929
DETERMINISM sillytavern repeats=5 identical=true sha=c9aaeea232804460d447e3b9084d85942bad8090adc4d9d819d0695078ff609c
DETERMINISM sillytavern repeats=5 identical=true sha=3b02affe3d0742c79286a994359e42d9d595294e9772ac7cc45883a00f7198dd
```

5 次都是独立 node 进程，stdout 与 `out/sillytavern_P*.json` 双双逐字节一致。ST 的概率判定（`world-info.js:5041`）与成组择一（`:5453`）走 `Math.random()`，本适配器在每次 `checkWorldInfo` 前按契约 `seed=20261014` 换成 `lcg32(seed + turn*1000003)` 并在调用后还原；不播种时同一输入的结果不保证一致。

### 4.5 预算口径与 maxContext（`raw/sillytavern_timing.txt`）

```
ENGINE_NOTE sillytavern profile=P0 max_context=16384 budget_tokens=4096 anchor_max_context=16384 budget_delta_vs_p0=0
ENGINE_NOTE sillytavern anchor_probe=256:binding,512:binding,1024:binding,2048:binding,4096:binding,8192:binding,16384:non-binding
ENGINE_NOTE sillytavern server_started=true server_wait_ms=3336 browser_ms=380 page_ready_ms=4124 evaluate_ms=466
```

- **P0 的 maxContext ＝ 16384，token 预算 4096**。取值规则：在 P0 档位设置下取最小的 2 的幂，使 6 个 turn 的注入集与 `maxContext=1000000` 的注入集逐 turn 完全相同。实测 8192 仍构成约束、16384 通过（上面的 `anchor_probe` 行）。
- **P3 的 maxContext ＝ 2458，token 预算 615**。取值规则：`round(16384 × 600 ÷ 4000)`，即按契约 §1.3 里 P3 与 P0 的预算比缩放锚点。
- P1／P2／P4 的 `budget_chars` 与 P0 同为 4000，共用锚点 16384。
- **P3 与基线的预算不可直接比字符数**：615 是 token，基线 600 是字符。可比的只有 dropped 条目集合。

### 4.6 逐条能力探针

- uid17（概率 50）：P0 turn3 起判不过、P2 turn3 判过（见 `raw/sillytavern_diff.txt` 的 P0vsP2 turn3 `only_b=17`），判定可复现。
- uid24（正则键 `/地.图/`）：ST 把键解析为正则（`world-info.js:2901`），`.` 要求 地 与 图 之间多一个字符，原文「地图」不匹配，故不激活；基线的字面串比较同样不匹配。两家激活集一致，理由不同。
- uid25（内容宏）：ST 在注入前调 `substituteParams`（`:5058`），正文被展开成 25 字符（夹具 39 字符）。`raw/sillytavern_content.txt` 逐字：

```
[RAW] adapter=sillytavern profile=P0 turn=3 uid=25 position=before_char depth=null chars=25 bytes=59 sha256=13763707e2e7b428680fc46cbadcdf49eb692cc893429dc4985e624e81aeeb87 content="内容宏探针：5 与 User 原样保留，不做替换。"
[RAW] adapter=sillytavern profile=P0 turn=4 uid=25 position=before_char depth=null chars=25 bytes=59 sha256=965f6f8351c68252c9988056485ee607aa57a519c63dce2b29ee9b3b891e94f8 content="内容宏探针：1 与 User 原样保留，不做替换。"
```

- uid8（条目级全词）在 P0 的注入正文（`raw/sillytavern_content.txt`）：

```
[RAW] adapter=sillytavern profile=P0 turn=1 uid=8 position=before_char depth=null chars=30 bytes=90 sha256=e0bf1b4f4f0fe9755f9e98d31174765f8997d02b338acd7146f3c0cc1d88ee4a content="单字全词条目：只在开启全词匹配的档位里才可能与中文正文对上。"
```

### 4.7 契约校验与代价

```
SUMMARY file=out/sillytavern_P0.json checks=58 fail=0
SUMMARY file=out/sillytavern_P1.json checks=58 fail=0
SUMMARY file=out/sillytavern_P2.json checks=59 fail=0
SUMMARY file=out/sillytavern_P3.json checks=60 fail=0
SUMMARY file=out/sillytavern_P4.json checks=58 fail=0
```

五档 `validate.py` 退出码全 0；唯一非 FAIL 的提示是 `NOTE C10-block-content` 对 uid25 的正文与夹具不同（宏展开，见 4.6）。

代价（M8，`raw/sillytavern_runner.txt` 与适配器 README 第二节）：`npm ci` 9 s／829 包；`upstream/node_modules` 337,045,122 字节／24,366 文件；`upstream/` 合计 474,833,878 字节；冷起服务 3,336 ms；单档端到端 p50 3,707 ms。

```
TIMING sillytavern profile=P0 min_ms=3718.14 p50_ms=3950.47 p95_ms=4114.21
TIMING sillytavern profile=P1 min_ms=3583.7 p50_ms=3707.68 p95_ms=4003.65
TIMING sillytavern profile=P2 min_ms=3483.79 p50_ms=3706.98 p95_ms=3980.58
TIMING sillytavern profile=P3 min_ms=3775.48 p50_ms=3909.11 p95_ms=4022.81
TIMING sillytavern profile=P4 min_ms=3894.24 p50_ms=3921.93 p95_ms=4199.57
```

## 5. 不适用条件

本适配器的读数只在下列条件下成立。

1. 契约预算以字符计，ST 的预算以 token 计且是 `maxContext` 的 25%；P3 与基线的预算不可直接比字符数，可比的只有 dropped 条目集合（契约 M3 本就是集合口径）。
2. ST 的成组择一与概率判定走 `Math.random()`；本适配器按契约 `seed` 播种后才可复现，不播种时同一输入不保证一致。
3. 窗口文本不含说话人名前缀（`world_info_include_names=false`），与基线 §2 规则 1 的口径一致。
4. 夹具 25 条全为 `delay=false`，且没有 sticky／cooldown，时间效果不参与读数。
5. 读数取的是 dry run（`checkWorldInfo(..., true)`），不进入生成流程，也不触发任何模型请求。

## 6. 未测项与原因

1. **提示词组装全链路（`PromptManager`、`openai.js` 生成前组装）未测**。原因：`PromptManager.getPromptCollection`／`render` 需要真实角色卡与生成入口驱动的状态，没有 dry-run 开关；本报告只声明世界书注入片段与注入顺序是确定性的。
2. **真实 LLM 生成面未测**。原因：契约禁止调用任何 LLM，运行期零凭据、不请求任何模型 API；世界书对生成结果的影响不在本报告范围内。
3. **`unsupported` 的 5 个字段全部未测**：`group_weight`（ST 组内仲裁是加权抽签，无「取最大权重」语义）、`recursion.delay`（契约 §2 未定义 delay 语义）、`capability_probe`（夹具标记）、`budget_chars`（口径不同）、`whole_words_cjk`（CJK 边界口径不同）。逐条依据见适配器 README 第五节。
4. **`npx playwright install chromium` 的完整体积与解压耗时未测**。原因：该命令在本机解压阶段挂死（2/2 复现，证据 `spike/st-roleplay/SPIKE.md` §4.3）；本次全部浏览器读数用 `CHROME_PATH` 指向已装 chrome 完成，未走该命令的产物。
5. **冷 npm 缓存下的安装耗时未测**。原因：本机缓存已热，`npm ci` 9 s 是热缓存值。
6. **`tests` 依赖的冷安装耗时未测**。原因：本次运行时依赖已就位，`npm install` 报 `up to date in 1s`。
7. **向量化世界书检索（`src/endpoints/vectors.js`）与宏引擎全链路未测**。原因：前者依赖外部 embedding 服务，违反零凭据约束；后者超出本契约的世界书触发面。
8. **上游自带 e2e 套件未复跑**。原因：本适配器的读数不依赖它；SPIKE 已记录 329 条用例中 328 通过、1 条 2/2 失败（`spike/st-roleplay/SPIKE.md` §3.3）。
