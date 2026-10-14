# txtai Workflow（任务管道）分片测评报告 v0.1

- 评测契约：`bench/cross_eval/harness/spec.md`（同一确定性五步流水线 load → index → retrieve → verify → emit；同一语料 200 篇 / 40 条查询；同一 BM25 实现；各自隔离 `--target`）。
- 被测对象：`bench/cross_eval/systems/txtai_impl.py`（本分片唯一实现文件）。
- 对照基线：`bench/cross_eval/harness/baseline.py`（手写实现，五模式）。
- 原始日志：`bench/cross_eval/raw/txtai_*`（本报告所有数字均直接取自这些文件，未做任何改写）。
- 本报告读数编号沿用共享词表 **M1–M8**（定义见 `docs/reviews/测评方法论_v0.1.md` §4）；§0 每条结论后面括号指向对应编号与原始文件。

---

## 0. 结论摘要

1. **产物一致性：五个模式全部与黄金产物逐字节一致。** sha256 = `8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd`，`lines=40`，`match=True`，覆盖 normal / resume / retry / sequential / parallel 五模式（M1，`raw/txtai_summary.json`、`raw/txtai_runner.txt`），并在离线复跑（M8，`raw/txtai_offline.txt`）与终态复跑（`raw/txtai_final.txt`）中各再得到一轮同样结果。
2. **编排单元数 = 5。** 每个 `Workflow` 实例挂 5 个 `Task`；normal/sequential/parallel 各建 1 个实例，resume 建 2 个，retry 建 3 个（M2，`raw/txtai_units.txt`）。
3. **实现规模：230 非空非注释行**，基线为 66 行（M2，`raw/txtai_loc.txt`，口径为 `harness/metrics.py:17-25` 的 `loc()`）。
4. **冷启动 import 代价：7428.7–7916.2 ms**（M3，`raw/txtai_coldstart.txt`）；同机基线依赖面（rank_bm25 + numpy）只需 177.4–215.0 ms（M3）。首次安装后未进页缓存的 import 为 32060.493 ms（M3，`raw/txtai_capability_probe.txt`）。
5. **稳态端到端 min/p50 与基线同一量级、互有胜负。** 主跑 txtai normal `min_ms 41.664 / p50_ms 52.629`（M3，`raw/txtai_runner.txt`）；交替三轮基线 normal `min_ms` 依次 32.972 / 55.627 / 36.136，txtai normal 依次 41.013 / 33.849 / 35.829（M6，`raw/txtai_timing_alt.txt`）。三轮里 txtai 胜 1 轮、负 2 轮。
6. **检查点/恢复：不支持。** `TXTAT_CAPABILITY checkpoint=unsupported`（M4，`raw/txtai_runner.txt`）；恢复路径为整段重跑，真实重跑名单 `["load", "index", "retrieve"]`（M4，`raw/txtai_resume.txt`），与基线行为相同。
7. **重试：不支持。** `Task(retries=3)` 抛 `TypeError: __init__() got unexpected keyword arguments: 'retries'`（M5，`raw/txtai_capability_probe.txt` B 段）；`attempts=3` 由调用方重新驱动 Workflow 得到（M5，`raw/txtai_retry.txt`）。
8. **扇出：支持，但作用域限于「同一 Task 内的多个 action」。** 4 个 action + `concurrency="thread"` + `workers=4`：312.6–414.3 ms / 4 个不同线程；同样 4 个 action 串行：1200.8–1236.8 ms（M6，`raw/txtai_capability_probe.txt` D 段）。**不存在数据元素级扇出。**
9. **本语料规模下扇出没有可复现的耗时收益。** sequential 与 parallel 的 min 差在 ±14 ms 内，且交替三轮方向不一致（M6，`raw/txtai_timing_alt.txt`：r1 seq 33.967 / par 42.201；r2 seq 42.354 / par 34.747；r3 seq 32.641 / par 47.82）。
10. **引擎自身的错误文本不点名步骤。** M7 探针（3 个 Task，第 2 个抛 `RuntimeError("boom")`）的引擎栈只到 `workflow/base.py:73 → :171 → task/base.py:95 → :122 → :297 → execute.py:61 → task/base.py:340`，无 Task 名/索引标记，末行仅 `RuntimeError: boom`（M7，`raw/txtai_capability_probe.txt` C 段）。
11. **依赖足迹 5.6 G**（M8，`raw/txtai_du.txt`），其中 torch 1.2 G、nvidia 3.2 G、triton 897 M，txtai 包本体仅 3.8 M；基线依赖面 70 M（M8）。
12. **零凭据、零联网可跑通五模式。** 显式置 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`、清空全部代理变量、环境中无任何 API_KEY/TOKEN 的情况下，五模式全部 `ok=True` 且 SHA 与黄金一致（M8，`raw/txtai_offline.txt`）。

---

## 1. 被测对象与版本

| 项 | 值 | 依据 |
|---|---|---|
| 引擎 | txtai **9.14.0** | `importlib.metadata.version('txtai')` → `9.14.0`（`raw/txtai_coldstart.txt`）；`/home/ubuntu/dm/pylibs/txtai/txtai-9.14.0.dist-info`（`raw/txtai_env.txt`） |
| 用到的子包 | `txtai.workflow`（`Workflow` + `Task`） | `bench/cross_eval/systems/txtai_impl.py:39` |
| 关键源码 | `txtai/workflow/base.py`（`Workflow`：`__call__`:51-76、`chunk`:125-154、`process`:156-174）；`txtai/workflow/task/base.py`（`Task`：`filteredrun`:99-132、`execute`:265-302、`hstack`:444-472）；`txtai/workflow/execute.py`（`Execute.run`:227-245、`pool`:247-271） | 源码路径 `/home/ubuntu/dm/pylibs/txtai/txtai/workflow/` |
| 实现文件 | `bench/cross_eval/systems/txtai_impl.py`，230 非空非注释行 | M2，`raw/txtai_loc.txt` |
| 对照基线 | `bench/cross_eval/harness/baseline.py`，66 非空非注释行 | M2，`raw/txtai_loc.txt` |
| 机器 | Ubuntu 24.04.5 LTS，kernel `6.18.33.2-microsoft-standard-WSL2`，`nproc=16`，`MemTotal: 7759520 kB`，`uid=1000` | `raw/txtai_env.txt` |
| Python | `/usr/bin/python3` → `Python 3.12.3` | `raw/txtai_env.txt` |

依赖版本（全部由 `importlib.metadata` 读出，`raw/txtai_coldstart.txt`）：

| 包 | 版本 | 位置 |
|---|---|---|
| txtai | 9.14.0 | `/home/ubuntu/dm/pylibs/txtai` |
| torch | 2.14.1 | `/home/ubuntu/dm/pylibs/txtai` |
| transformers | 5.19.0 | `/home/ubuntu/dm/pylibs/txtai` |
| rank_bm25 | 0.2.2 | `/home/ubuntu/dm/pylibs/base` |
| numpy | 2.5.4 | `/home/ubuntu/dm/pylibs/base` |

注：顶层 `txtai` 包不导出 `__version__`（`import txtai; txtai.__version__` → `AttributeError: module 'txtai' has no attribute '__version__'`，见 `raw/txtai_env.txt`），故版本一律以 `importlib.metadata` 与 `dist-info` 目录名为准。

**实现要点（每一步用到的引擎 API，逐字对应源码注释）：**

| 步骤 | 用到的 txtai API |
|---|---|
| load | `Task(action=[run.step_load], unpack=True)`（`txtai_impl.py:194`）；批由 `Workflow.chunk`（`base.py:125-154`）切出 |
| index | `Task(action=[run.step_index], unpack=True)`（`txtai_impl.py:195`） |
| retrieve（串行） | `Task(action=[run.step_retrieve], unpack=True)`（`txtai_impl.py:201`） |
| retrieve（并行） | `Task(action=run.retrieve_actions(workers), concurrency="thread", unpack=True)`（`txtai_impl.py:199`）+ `Workflow(workers=4)`（`txtai_impl.py:206`）；并发由 `task/base.py:296-297 → execute.py:239 → execute.py:258-262` 的 `ThreadPool` 提供 |
| verify | `Task(action=[run.step_verify], unpack=True)`（`txtai_impl.py:203`）；N 个 action 的输出经 `hstack`（`task/base.py:444-472`）合并为 `(s0..sN)` 元组 |
| emit | `Task(action=[run.step_emit], unpack=True)`（`txtai_impl.py:204`） |

五步的函数体全部调用 `workload` 的纯函数：`workload.step_load`（`txtai_impl.py:116`）、`workload.step_index`（:123）、`workload.step_retrieve`（:131、:146）、`workload.step_verify`（:179）、`workload.step_emit`（:187）；检索算法与基线、与其它引擎分片完全一致。

---

## 2. 复现步骤

### 2.1 环境

- WSL2 Ubuntu 24.04.5 LTS，kernel `6.18.33.2-microsoft-standard-WSL2`，`nproc=16`，`MemTotal: 7759520 kB`（`raw/txtai_env.txt`）。
- `/usr/bin/python3` = Python 3.12.3（`raw/txtai_env.txt`）。
- 引擎与依赖预置在 `/home/ubuntu/dm/pylibs/txtai`（txtai 9.14.0、torch 2.14.1、transformers 5.19.0）与 `/home/ubuntu/dm/pylibs/base`（rank_bm25 0.2.2、numpy 2.5.4）。
- 运行时环境变量（**必须**，否则 `import txtai` / `rank_bm25` 失败）：

```bash
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
```

### 2.2 依赖安装命令（逐字）

本次测评**没有执行任何安装命令**：引擎与依赖由评测发起方预置，本次只读取 `/home/ubuntu/dm/pylibs/*`，未改动、未重装、未补装任何包。

若需要重建同机环境，任务书给出的镜像安装模板（**本次未执行**，故不列出未经执行的完整包名清单）：

```bash
python3 -m pip install --break-system-packages --target /home/ubuntu/dm/pylibs/txtai -i https://pypi.tuna.tsinghua.edu.cn/simple <pkg>
```

版本锚点以上表为准；可用以下命令核对（本次已执行，输出见 `raw/txtai_coldstart.txt`）：

```bash
python3 -c "import importlib.metadata as m; print(m.version('txtai'), m.version('torch'), m.version('rank_bm25'), m.version('numpy'))"
```

### 2.3 复跑命令（逐字）

主跑（产生 M1/M3/M4/M5 与 `raw/txtai_summary.json`）：

```bash
cd /mnt/d/lingshu-memory-plugin/cross-eval-20261014
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
python3 -X utf8 bench/cross_eval/harness/runner.py --impl bench/cross_eval/systems/txtai_impl.py --name txtai --modes normal,resume,retry,sequential,parallel 2>&1 | tee bench/cross_eval/raw/txtai_runner.txt
```

辅助读数（各自产出一份 raw 文件）：

```bash
bash bench/cross_eval/raw/txtai_env.sh        # -> raw/txtai_env.txt（环境）
bash bench/cross_eval/raw/txtai_coldstart.sh  # -> raw/txtai_coldstart.txt（M3 冷启动 import）
bash bench/cross_eval/raw/txtai_loc.sh        # -> raw/txtai_loc.txt（M2 行数）
bash bench/cross_eval/raw/txtai_du.sh         # -> raw/txtai_du.txt（M8 依赖足迹）
bash bench/cross_eval/raw/txtai_capability_probe.sh  # -> raw/txtai_capability_probe.txt（M4/M5/M6/M7 能力证据）
bash bench/cross_eval/raw/txtai_alt.sh        # -> raw/txtai_timing_alt.txt（M6 交替计时）
bash bench/cross_eval/raw/txtai_offline.sh    # -> raw/txtai_offline.txt（M8 零凭据复跑）
PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai python3 -X utf8 bench/cross_eval/raw/txtai_units.py | tee bench/cross_eval/raw/txtai_units.txt  # -> M2 编排单元数
```

### 2.4 预期耗时

| 动作 | 预期耗时 | 实测依据 |
|---|---|---|
| 单次五模式主跑 | 约 15–25 s（每次进程启动 import txtai 7.4–7.9 s，随后每模式 `timeit` 1 次预热 + 7 次重复，单次 30–90 ms） | M3 |
| 全量复跑本报告全部读数 | 约 6–8 分钟 | 各 raw 文件的 `ls -la` 时间戳：08:43 → 09:03 |

---

## 3. 基线 vs 方案对照读数

### 3.1 逐项对照表

主跑读数（各 1 次预热 + 7 次重复；基线数字为评测发起方提供的已跑通读数，方案数字为本次实测 M3）：

| 指标 | 基线（手写） | txtai Workflow | 读数编号 |
|---|---|---|---|
| 产物 sha256 | `8454e1f3…40bd`（黄金） | `8454e1f3…40bd`，match=True，40 行 | M1 |
| 非空非注释行数 | 66 | 230 | M2 |
| 编排单元数 | 5 个步骤函数（`_load_index` / `_fanout` / `_finish` + `run` 内联） | 5 个 `Task` | M2 |
| normal min / p50 (ms) | 41.977 / 60.849 | **41.664 / 52.629** | M3 |
| sequential min / p50 (ms) | 45.435 / 58.373 | **46.008 / 60.87** | M3 |
| parallel min / p50 (ms) | 50.92 / 58.483 | **40.163 / 56.315** | M3 |
| 冷启动 import (ms) | 177.4–215.0（rank_bm25+numpy） | **7428.7–7916.2**（txtai.workflow） | M3 |
| resume 重跑步骤 | `["load","index","retrieve"]` | `["load","index","retrieve"]` | M4 |
| retry 尝试次数 | 3 | 3 | M5 |
| 引擎错误是否点名步骤 | 否（基线自写异常） | 否 | M7 |
| 依赖足迹 | 70 M | 5.6 G | M8 |
| CAPS.checkpoint / retry / fanout | False / False / True | False / False / True | `raw/txtai_summary.json` |

交替计时（M6，baseline 与 txtai 轮流各跑 3 轮，每轮 1 预热 + 7 重复；`min_ms / p50_ms / p95_ms`）：

| 轮次 | 模式 | 基线 | txtai |
|---|---|---|---|
| r1 | normal | 32.972 / 47.181 / 51.152 | 41.013 / 51.837 / 64.454 |
| r1 | sequential | 46.689 / 50.17 / 59.653 | 33.967 / 43.321 / 122.812 |
| r1 | parallel | 35.234 / 58.771 / 98.422 | 42.201 / 52.161 / 64.913 |
| r2 | normal | 55.627 / 87.649 / 181.137 | 33.849 / 49.801 / 53.805 |
| r2 | sequential | 50.39 / 56.528 / 64.428 | 42.354 / 46.226 / 61.865 |
| r2 | parallel | 45.163 / 65.946 / 83.378 | 34.747 / 53.501 / 97.911 |
| r3 | normal | 36.136 / 41.151 / 46.478 | 35.829 / 45.938 / 50.086 |
| r3 | sequential | 30.778 / 35.249 / 105.015 | 32.641 / 42.511 / 55.703 |
| r3 | parallel | 39.208 / 47.657 / 54.876 | 47.82 / 51.342 / 55.437 |

### 3.2 原始输出片段（逐字复制，未改写任何数字）

`raw/txtai_runner.txt`（主跑，M1/M3/M4/M5 的原始出处）：

```text
IMPL bench/cross_eval/systems/txtai_impl.py NAME txtai
CAPS {"checkpoint": false, "fanout": true, "note": "fanout=True 指 txtai 内建线程/进程池（task/base.py:296-297 -> execute.py:239/258-262），作用域为同一 Task 内的多个 action，无元素级扇出；checkpoint=False（workflow/ 目录 grep checkpoint|resume|restart 0 命中，Workflow 无 save/load）；retry=False（Task(retries=3) -> TypeError: __init__() got unexpected keyword arguments: 'retries'）", "retry": false}
RUN mode=normal ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
TXTAT_CAPABILITY checkpoint=unsupported evidence='txtai 9.14.0: grep -ri checkpoint|resume|restart txtai/workflow/ -> 0 hits; Workflow has no save/load'; recovery=rerun_whole_workflow first_pass_counts={'load': 1, 'index': 1, 'retrieve': 1}
TXTAT_RESTART counts={'load': 2, 'index': 2, 'retrieve': 2, 'verify': 1, 'emit': 1} raw_trace=['load', 'index', 'retrieve', 'load', 'index', 'retrieve', 'verify', 'emit'] reexecuted=['load', 'index', 'retrieve']
RUN mode=resume ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "load", "index", "retrieve", "verify", "emit"]
FIRST_ERROR injected failure at verify
REEXECUTED ["load", "index", "retrieve"]
TXTAT_CAPABILITY retry=unsupported evidence="Task(retries=3) -> TypeError: __init__() got unexpected keyword arguments: 'retries'"; attempts=3 verify_entries=3 counts={'load': 3, 'index': 3, 'retrieve': 3, 'verify': 1, 'emit': 1}
RUN mode=retry ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "load", "index", "retrieve", "load", "index", "retrieve", "verify", "emit"]
ATTEMPTS 3
ERROR_TEXT injected transient failure
RUN mode=sequential ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
TXTAT_FANOUT mode=parallel actions=4 workers=4 retrieve_invocations=4 distinct_threads=2 thread_ids=[135565719627456, 135565728020160]
RUN mode=parallel ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
TIMING normal {"min_ms": 41.664, "n": 7, "p50_ms": 52.629, "p95_ms": 56.784}
TIMING sequential {"min_ms": 46.008, "n": 7, "p50_ms": 60.87, "p95_ms": 86.884}
TIMING parallel {"min_ms": 40.163, "n": 7, "p50_ms": 56.315, "p95_ms": 71.955}
SUMMARY_WRITTEN raw/txtai_summary.json
```

`raw/txtai_parallel.txt`（M6 的 runner 侧落盘，与上面的 TXTAT_FANOUT 行对应）：

```text
RUN mode=parallel ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
```

`raw/txtai_capability_probe.txt` D 段（M6 扇出作用域）：

```text
### D. 并发原语作用域探针：单 action 任务是否并发（对照 4 action）
每个 action sleep 0.30s；期望：4 action 串行 ~1200ms，4 action 并发 ~300ms
1 action  concurrency=None               elapsed_ms=   300.3  invocations=1  distinct_threads=1
4 action  concurrency=None (串行)          elapsed_ms=  1200.8  invocations=4  distinct_threads=1
4 action  concurrency=thread w=4         elapsed_ms=   312.6  invocations=4  distinct_threads=4
每个 action sleep 0.30s；期望：4 action 串行 ~1200ms，4 action 并发 ~300ms
1 action  concurrency=None               elapsed_ms=   312.0  invocations=1  distinct_threads=1
4 action  concurrency=None (串行)          elapsed_ms=  1236.8  invocations=4  distinct_threads=1
4 action  concurrency=thread w=4         elapsed_ms=   348.4  invocations=4  distinct_threads=4
4 action  concurrency=process w=4        -> RuntimeError: 
每个 action sleep 0.30s；期望：4 action 串行 ~1200ms，4 action 并发 ~300ms
1 action  concurrency=None               elapsed_ms=   311.1  invocations=1  distinct_threads=1
4 action  concurrency=None (串行)          elapsed_ms=  1231.4  invocations=4  distinct_threads=1
4 action  concurrency=thread w=4         elapsed_ms=   414.3  invocations=4  distinct_threads=4
4 action  concurrency=process w=4        -> RuntimeError: 
4 action  concurrency=process w=4        -> AttributeError: Can't pickle local object 'mk_actions.<locals>.mk.<locals>.<lambda>'
```

`raw/txtai_offline.txt`（M8 零凭据/零联网复跑）：

```text
IMPL bench/cross_eval/systems/txtai_impl.py NAME txtai_offline
CAPS {"checkpoint": false, "fanout": true, "note": "fanout=True 指 txtai 内建线程/进程池（task/base.py:296-297 -> execute.py:239/258-262），作用域为同一 Task 内的多个 action，无元素级扇出；checkpoint=False（workflow/ 目录 grep checkpoint|resume|restart 0 命中，Workflow 无 save/load）；retry=False（Task(retries=3) -> TypeError: __init__() got unexpected keyword arguments: 'retries'）", "retry": false}
RUN mode=normal ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
RUN mode=resume ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "load", "index", "retrieve", "verify", "emit"]
FIRST_ERROR injected failure at verify
REEXECUTED ["load", "index", "retrieve"]
RUN mode=retry ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "load", "index", "retrieve", "load", "index", "retrieve", "verify", "emit"]
ATTEMPTS 3
ERROR_TEXT injected transient failure
RUN mode=sequential ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
RUN mode=parallel ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
TIMING normal {"min_ms": 35.682, "n": 7, "p50_ms": 39.385, "p95_ms": 46.968}
TIMING sequential {"min_ms": 32.089, "n": 7, "p50_ms": 46.075, "p95_ms": 57.409}
TIMING parallel {"min_ms": 41.807, "n": 7, "p50_ms": 51.504, "p95_ms": 74.83}
```

---

## 4. 读数明细

（按 spec.md 的 M1–M8 逐项）

### M1 产物正确性（逐字节与基线一致）

- 五模式 `sha256 = 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd`，`lines=40`，`match=True`（`raw/txtai_runner.txt`、`raw/txtai_summary.json` 的 `modes.*.matches_golden` 全为 `true`）。
- 独立复跑 1（`raw/txtai_offline.txt`，离线 + 无代理）：五模式同样 `match=True`。
- 独立复跑 2（`raw/txtai_timing_alt.txt`，交替三轮）：每轮基线侧与 txtai 侧均 `match=True lines=40`。
- 独立复跑 3（`raw/txtai_final.txt`，实现文件定稿后的终态复跑）：五模式同样 `match=True lines=40`。
- 合计 **15 次独立产出**（主跑 5 + 离线 5 + 终态 5）与黄金产物逐字节一致，无一次偏差。

### M2 实现规模与编排单元数

- M2（`raw/txtai_loc.txt`）：`loc(bench/cross_eval/systems/txtai_impl.py) = 230`；`loc(bench/cross_eval/harness/baseline.py) = 66`。
  - 口径：`harness/metrics.py:17-25` 的 `loc()` = 非空且不以 `#` 开头的行数。
  - **与任务书提供的「基线 LOC 44」不一致**：本次用同一 `metrics.loc` 实测 `baseline.py` 为 66。可能是版本或统计口径差异；本报告一律以实测 66 为准，并如实标出该差异。
- M2（`raw/txtai_units.txt`，用 monkeypatch 记录 `Workflow.tasks` 长度）：

```text
mode=normal      ok=True Workflow实例数=1 每个实例Task数=[5]
mode=resume      ok=True Workflow实例数=2 每个实例Task数=[5, 5]
mode=retry       ok=True Workflow实例数=3 每个实例Task数=[5, 5, 5]
mode=sequential  ok=True Workflow实例数=1 每个实例Task数=[5]
mode=parallel    ok=True Workflow实例数=1 每个实例Task数=[5]
```

- 结论：编排单元数 = **5 个 Task**；resume 通过「再建一个 5-Task Workflow 整段重跑」实现，retry 通过「重建 3 次」实现。

### M3 冷启动与端到端耗时

M3 冷启动 import（每个新进程独立测量，`raw/txtai_coldstart.txt`）：

| 被测 | 样本 1 | 样本 2 | 样本 3 |
|---|---|---|---|
| `import txtai` | 7525.4 ms | 7428.7 ms | 7473.8 ms |
| `from txtai.workflow import Task, Workflow` | 7896.8 ms | 7862.7 ms | 7916.2 ms |
| `import torch`（单独进程） | 2394.8 ms | 2801.9 ms | 2353.8 ms |
| `import rank_bm25, numpy`（基线依赖面） | 215.0 ms | 177.4 ms | 208.3 ms |
| `import txtai`（安装后首次，页缓存冷） | 32060.493 ms | — | — |

M3 端到端（主跑，`raw/txtai_runner.txt`，`n=7`，含 1 次预热）：

| 模式 | min_ms | p50_ms | p95_ms |
|---|---|---|---|
| normal | 41.664 | 52.629 | 56.784 |
| sequential | 46.008 | 60.87 | 86.884 |
| parallel | 40.163 | 56.315 | 71.955 |

M6 交替计时三轮见 §3.1 表（`raw/txtai_timing_alt.txt`）；M8 离线复跑 normal min 35.682 / p50 39.385 / p95 46.968。

要点：端到端耗时（几十毫秒）与冷启动 import（7–8 秒）相差两个数量级；在「进程内重复调用」的测量口径下，import 代价被预热排除，因此 M3 的 min/p50 与基线同量级，而真实的一次性进程调用中 import 占绝对主导。

### M4 断点续跑：重跑了哪些步骤

- `raw/txtai_resume.txt` 逐字：

```text
RUN mode=resume ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "load", "index", "retrieve", "verify", "emit"]
FIRST_ERROR injected failure at verify
REEXECUTED ["load", "index", "retrieve"]
```

- 真实执行计数（`raw/txtai_runner.txt` 的 `TXTAT_RESTART` 行）：`counts={'load': 2, 'index': 2, 'retrieve': 2, 'verify': 1, 'emit': 1}`。
- 重跑名单**来自真实轨迹**：`_Run.record()`（`txtai_impl.py:97-101`）在每个节点进入时累加计数，`reexecuted = [s for s in STEPS if counts[s] > 1]`（`txtai_impl.py:255`），非硬编码。
- 引擎侧能力结论：`checkpoint=unsupported`。依据（`raw/txtai_capability_probe.txt` A/B 段）：`grep -rn -iE 'checkpoint|resume|restart' txtai/workflow/` → 0 命中；`Workflow` 公开 API 仅 `['chunk','finalize','initialize','process','schedule']`；`hasattr save/load/checkpoint/resume: False False False False`；`Workflow(checkpoint=True)` → `TypeError: Workflow.__init__() got an unexpected keyword argument 'checkpoint'`。
- 与基线一致：基线 resume 同样整段重跑 `["load","index","retrieve"]`。

### M5 重试的真实尝试次数

- `raw/txtai_retry.txt` 逐字：

```text
RUN mode=retry ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "load", "index", "retrieve", "load", "index", "retrieve", "verify", "emit"]
ATTEMPTS 3
ERROR_TEXT injected transient failure
```

- `attempts=3` 是真实驱动次数（`txtai_impl.py:270-277` 的 `attempts += 1` 与 `_execute` 调用一一对应），`verify_entries=3`、`counts={'load': 3, 'index': 3, 'retrieve': 3, 'verify': 1, 'emit': 1}`（`raw/txtai_runner.txt` 的 `TXTAT_CAPABILITY retry=unsupported` 行）。
- 引擎侧能力结论：`retry=unsupported`。依据：`Task(retries=3)` → `TypeError: __init__() got unexpected keyword arguments: 'retries'`；`Task(retry=3)` 同形；`Task(on_error=...)` 同形；`grep -rn -iE 'retry|retries|backoff' txtai/workflow/` → 0 命中（`raw/txtai_capability_probe.txt` A/B 段）。
- 因此本模式的 `while True` 重驱动循环是**调用方自写**，不是引擎能力；报告与 `CAPS.note` 均已如实标注「引擎无内建重试，需自行实现」。

### M6 并发 vs 串行

- 能力（`raw/txtai_capability_probe.txt` D 段）：4 个 action `concurrency=None` = 1200.8 / 1236.8 / 1231.4 / 1204.2 / 1205.2 ms，1 线程；4 个 action `concurrency="thread"` + `workers=4` = 312.6 / 348.4 / 414.3 / 358.0 / 364.0 ms，4 个不同线程。⇒ txtai 的线程池确实并发，但作用域是「同一 Task 内的多个 action」。
- 元素级扇出：**不存在**。`concurrency="process"` 需要可 pickle 的 action，lambda 直接 `AttributeError: Can't pickle local object 'mk_actions.<locals>.mk.<locals>.<lambda>'`（另有 spawn 引导期 `RuntimeError`）。
- 效果（本语料 40 条查询 / 200 篇文档，BM25 检索本身只需几毫秒）：
  - 主跑 M3：sequential min 46.008 / parallel min 40.163（parallel 少 5.845 ms）。
  - 交替 M6：r1 seq 33.967 vs par 42.201（par 多 8.234 ms）；r2 seq 42.354 vs par 34.747（par 少 7.607 ms）；r3 seq 32.641 vs par 47.82（par 多 15.179 ms）。
  - ⇒ 三轮方向不一致，差值在 ±16 ms 内，**本语料规模下无可复现收益**；线程池调度与分片拼接的开销与检索耗时同量级。
- parallel 模式的真实线程证据：`TXTAT_FANOUT mode=parallel actions=4 workers=4 retrieve_invocations=4 distinct_threads=2 thread_ids=[135565719627456, 135565728020160]`（`raw/txtai_runner.txt`）；终态复跑同一行为 `distinct_threads=4 thread_ids=[124605338470080, 124605346862784, 124605355255488, 124605363648192]`（`raw/txtai_final.txt`）。即 4 个 action 全部被调用，观测到的不同线程数为 2–4（线程池复用导致跨轮波动）。

### M7 失败时错误文本是否点名步骤

- 探针 `raw/txtai_probe_m7.py`：3 个 `Task`，第 2 个抛 `RuntimeError("boom")`。引擎栈（`raw/txtai_capability_probe.txt` C 段）逐字：

```text
  File "/home/ubuntu/dm/pylibs/txtai/txtai/workflow/base.py", line 73, in __call__
    yield from self.process(batch, executor)
  File "/home/ubuntu/dm/pylibs/txtai/txtai/workflow/base.py", line 171, in process
    elements = task(elements, executor)
  File "/home/ubuntu/dm/pylibs/txtai/txtai/workflow/task/base.py", line 95, in __call__
    return self.filteredrun(elements, executor)
  File "/home/ubuntu/dm/pylibs/txtai/txtai/workflow/task/base.py", line 122, in filteredrun
    results = self.execute([self.prepare(element) for _, element in data], executor)
  File "/home/ubuntu/dm/pylibs/txtai/txtai/workflow/task/base.py", line 297, in execute
    outputs = executor.run(self.concurrency, self.process, outputs)
  File "/home/ubuntu/dm/pylibs/txtai/txtai/workflow/execute.py", line 61, in run
    return [function(*arg) for arg in args]
  File "/home/ubuntu/dm/pylibs/txtai/txtai/workflow/task/base.py", line 340, in process
    outputs = action(inputs)
RuntimeError: boom
```

- 探针结论行：`contains Task-name marker : False`；`last line : RuntimeError: boom`。
- 即：**引擎自身的错误文本不点名步骤**（无 Task 名、无索引、无 `Task #` 标记），只能靠栈里的 `task/base.py` 帧区分「引擎内部」与「用户 action」，无法定位是第几个步骤。
- 本实现里的 `FIRST_ERROR injected failure at verify` / `ERROR_TEXT injected transient failure` 是**我们自己注入的异常字符串**，不能作为引擎能力的证据。

### M8 依赖足迹与零凭据可运行性

M8（`raw/txtai_du.txt`）：

| 路径 | 大小 |
|---|---|
| `/home/ubuntu/dm/pylibs/txtai`（总计） | 5.6 G |
| ├ `nvidia` | 3.2 G |
| ├ `torch` | 1.2 G |
| ├ `triton` | 897 M |
| ├ `transformers` | 116 M |
| ├ `sympy` | 74 M |
| ├ `numpy` | 43 M |
| └ `txtai`（包本体） | 3.8 M |
| `/home/ubuntu/dm/pylibs/base`（基线依赖面） | 70 M |

M8（`raw/txtai_offline.txt`）：显式 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1`、`http_proxy= https_proxy= all_proxy= ... no_proxy=*`，且 `env | grep -iE 'API_KEY|TOKEN|SECRET|OPENAI|ANTHROPIC'` → `(none)` 的条件下，五模式全部 `ok=True`、SHA 与黄金一致。⇒ 本方案在**零凭据、零联网**下可完整复跑。

---

## 5. 不适用条件

以下条件下本分片方案（`systems/txtai_impl.py` + txtai 9.14.0）**不适用或不成立**：

1. **要求真正的断点续跑 / 检查点恢复时**：txtai Workflow 无任何检查点 API（M4 依据）。若业务要求「失败后只重跑失败步骤」，本方案做不到，只能整段重跑（与基线同样代价）。
2. **要求引擎内建重试 / 退避策略时**：Task 不接受 `retries` / `retry` / `on_error` 参数（M5 依据）。重试必须由调用方实现，属「引擎无内建 X，需自行实现」。
3. **要求数据元素级扇出（逐条查询并发）时**：txtai 的并发原语只作用于「同一 Task 内的多个 action」（M6 依据），必须人为把数据切成 N 片再交给 N 个 action；片数一旦变化，分片拼接逻辑（`txtai_impl.py:143-146`）需要跟着改。
4. **要求多进程（非线程）并行时**：`concurrency="process"` 走 `torch.multiprocessing` 的 spawn 上下文（`execute.py:264-267`），要求 action 可 pickle；闭包/lambda 直接抛 `AttributeError: Can't pickle local object ...`（M6 依据）。
5. **要求低依赖足迹 / 小镜像 / 边缘部署时**：5.6 G（其中 GPU 相关 4.4 G，M8）是本方案相对基线的**额外前置条件**；基线只需 70 M。
6. **要求毫秒级冷启动 / serverless 短进程时**：单次进程 import 需 7.4–7.9 s，首次 32.06 s（M3）；本方案的端到端毫秒级读数只在「进程内预热后重复调用」口径下成立。
7. **要求跨进程共享检索索引时**：本实现的索引存在进程内 state dict 里，不落盘、不共享；引擎无 save/load（M4 依据）。
8. **需要 LLM 语义检索 / 向量检索时**：本分片按契约只调用 `workload` 的 BM25 纯函数，未使用 txtai 的 `Embeddings` / `RAG` / `pipeline` 能力（见 §6）。
9. **无 GPU 且不允许下载 CUDA 轮子时**：torch 2.14.1+cu130 与 nvidia_* 包为预置依赖；本方案实际只用 CPU（未调用任何 CUDA 算子），但依赖体积与安装条件仍在。

相对基线的额外前置条件：额外需要 `PYTHONPATH` 指向 txtai/torch 的安装目录（§2.1），基线只需 `rank_bm25` + `numpy`。

---

## 6. 未测项与原因

| 未测项 | 原因 |
|---|---|
| txtai 的 LLM 调用面（`LLM`、`RAG`、`Textractor`、`pipeline("summary"/"textractor")` 等） | 评测环境**无任何 LLM/API 凭据**且禁止联网调外部 API（任务书约束）；本分片按契约只用 `txtai.workflow` 的编排能力 |
| txtai 的向量检索（`Embeddings`、`SentenceTransformer` 模型下载） | 需要从 HuggingFace 下载模型权重，违反「不联网」约束；且契约要求四家共用同一 BM25 检索器，换检索算法会使对照不公平 |
| 网络相关的 Workflow Task（`UrlTask`、`ServiceTask`、`ConsoleTask` 的远程端点） | 同上，需要外部网络 |
| 分布式 / 多进程持久化后端（`schedule()` 定时、跨进程恢复） | 引擎本身无检查点/持久化 API（M4）；`Workflow.schedule` 依赖 `croniter`，本次未安装该包，也未在无头环境验证定时语义 |
| 多进程（spawn）扇出的端到端效果 | `concurrency="process"` 在本实现的闭包 action 上不可用（M6 的 pickle 报错）；改用模块级可 pickle 函数属另一套实现，超出本次分片范围 |
| GPU 路径（CUDA 算子、`torch.cuda`） | 本方案的五个步骤全是 CPU 上的纯 Python/BM25 计算，未触发任何 GPU 算子；GPU 相关包只贡献体积（M8） |
| 更大语料下的扇出收益 | 本次语料为契约固定的 200 篇 / 40 条查询，检索耗时本身只有几毫秒，无法体现并发的收益边界（M3/M6 已给出「本规模下无收益」的读数） |
| 与其它引擎分片的交叉复核 | 属 Lead 的收口范围，不在本分片写域内 |
