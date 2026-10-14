# LlamaIndex Workflows 分片测评报告 v0.1

- 分片：横向测评 `cross-eval-20261014` 的 **LlamaIndex Workflows（事件驱动工作流）** 一路。
- 被测对象、工作负载、读数口径由 `bench/cross_eval/harness/spec.md`（冻结版 v0.1）规定；本报告只补充本分片的实现与读数。
- 本报告出现的每一个数字都取自 `bench/cross_eval/raw/llamaindex_*` 或 `bench/cross_eval/raw/baseline_runner.txt` 的原始输出；未落进原始文件的数字不写入本报告。
- 五步流水线一律调用 `bench/cross_eval/harness/workload.py` 的纯函数（`step_load` / `step_index` / `step_retrieve` / `step_verify` / `step_emit` / `load_queries`），检索算法与基线、与其它两家完全同一份。

## 0. 结论摘要

1. **M1 正确性通过。** 五个模式（normal / resume / retry / sequential / parallel）的 emit 产物 sha256 均为 `8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd`，与黄金产物 `match=True`，40 行（raw/llamaindex_runner.txt:4,7,12,16,19）。
2. **M2 构建成本高于基线。** `metrics.loc`：本实现 238 行 vs 基线 `baseline.py` 66 行，比值 3.606×；编排单元（`@step` 数）本实现 7 vs 基线 0（raw/llamaindex_meta.txt:13-20）。
3. **M3 冷启动代价显著。** 交替各 5 次独立进程：基线 106.2–134.3 ms，本方案 3006.7–3754.1 ms，min 倍率 28.312×（raw/llamaindex_coldimport.txt）。
4. **M3 端到端耗时高于基线。** normal min/p50 = 151.262 / 167.71 ms（基线 55.585 / 62.665 ms），min 倍率 2.721×、p50 倍率 2.676×；sequential min 倍率 3.702×、parallel min 倍率 4.236×（raw/llamaindex_runner.txt:21-23 vs raw/baseline_runner.txt:21-23）。
5. **M4 断点续跑：引擎能只重跑未完成的部分。** 注入失败后恢复，`steps_reexecuted_after_failure = ["verify","emit"]`，恢复后 load/index/retrieve 的执行计数均为 0（raw/llamaindex_meta.txt:43）；基线同场景重跑 `["load","index","retrieve"]`（raw/baseline_runner.txt:10）。
6. **M5 重试：真实尝试次数 = 3。** `ATTEMPTS 3`（raw/llamaindex_runner.txt:13）。作用域说明：计的是 **verify 这一个 step 的单次执行** 的尝试次数（`workflows/decorators.py:127` 的 `retry_policy` 挂在单个 step 上），不是整条 workflow 的重跑次数；基线的 3 是 `while` 循环里整步重试的次数，两者都等于 3，但作用域不同。
7. **M6 并发扇出没有缩短耗时。** 专项读数 parallel/sequential min 比 = 1.072、p50 比 = 0.842（raw/llamaindex_meta.txt:40-41）：在 40 条查询、单条 BM25 查询耗时极小的负载上，引擎的事件调度与线程池开销大于并行收益。基线同负载 parallel/sequential min 比 = 0.968（raw/baseline_runner.txt:22-23），同样没有收益。
8. **M7 错误文本不点名步骤。** `str(exc) = 'injected failure at verify'`，其中 "verify" 来自注入消息本身、不是引擎添加的；引擎在 `workflows/runtime/control_loop/runner.py:367` 原样 `raise command.exception`。回溯里可见 step 帧 `llamaindex_impl.py:203 in s_verify`（raw/llamaindex_m7.txt）。
9. **M8 依赖足迹 247M**（另加共用的 base 70M，raw/llamaindex_m8.txt）；零 LLM 凭据（`credential_like_env_count = 0`）、封死 socket 建连后仍跑通且 sha256 不变（`network_connect_attempts = 0`，raw/llamaindex_m8.txt）。
10. **能力认定（对应 M4 / M5 / M6 三项）：checkpoint / retry / fanout 均有引擎 API 依据，本分片没有"不支持"项。** 依据见 §1 的 API 表（逐条给已装版本源码 `文件:行号`）；三项能力各自的实测读数见 §4 的 M4 / M5 / M6。本实现自行添加的唯一同步是 resume 探针的 asyncio.Event 握手，已在 §4 M4 注明，不计入引擎能力。

## 1. 被测对象与版本

**引擎**：LlamaIndex Workflows（事件驱动工作流）。

| 发行版 | 版本 | 证据 |
|---|---|---|
| llama-index-core | 0.14.25 | `/home/ubuntu/dm/pylibs/llamaindex/llama_index_core-0.14.25.dist-info`（raw/llamaindex_m8.txt） |
| llama-index-workflows | 2.26.0 | `/home/ubuntu/dm/pylibs/llamaindex/llama_index_workflows-2.26.0.dist-info`（raw/llamaindex_m8.txt） |
| llama-index-instrumentation | 0.6.0 | `/home/ubuntu/dm/pylibs/llamaindex/llama_index_instrumentation-0.6.0.dist-info`（raw/llamaindex_m8.txt） |
| rank_bm25（四家共用检索器） | 0.2.2 | `/home/ubuntu/dm/pylibs/base/rank_bm25-0.2.2.dist-info` |
| numpy（rank_bm25 依赖） | 2.5.4 | `/home/ubuntu/dm/pylibs/base/numpy-2.5.4.dist-info` |

**运行时**：`/usr/bin/python3` = Python 3.12.3 (main, Aug 31 2026, 10:18:26) [GCC 13.3.0]；Linux 6.18.33.2-microsoft-standard-WSL2 x86_64 GNU/Linux（raw/llamaindex_meta.txt:121-122）。

**实现文件**：`bench/cross_eval/systems/llamaindex_impl.py`，`metrics.loc` = 238（非空非注释行数）。

**代码里实际使用的 import 路径**：

```python
from llama_index.core.workflow import Context, Event, StartEvent, StopEvent, Workflow, step
from workflows.retry_policy import retry_policy, retry_if_exception_type, stop_after_attempt, wait_none
```

说明：`llama_index.core.workflow` 是 `workflows` 包的转发层，顶层导出 `Context / Event / StartEvent / StopEvent / Workflow / WorkflowRuntimeError / WorkflowTimeoutError / WorkflowValidationError / step / InputRequiredEvent / HumanResponseEvent / JsonPickleSerializer / JsonSerializer`，**不转发** `retry_policy()` 组合工厂，所以重试策略直接从 `workflows.retry_policy` 导入（同一 wheel 内）。

**被用到的引擎 API 与源码位置（已装版本，逐条给出 `文件:行号`）**：

| 能力 | 引擎 API | 源码位置 | 本实现使用处 |
|---|---|---|---|
| 扇出 | `@step` 返回 `list[Event]`，每个元素成为独立事件流 | `workflows/runtime/types/step_function.py:305`（"A step that actually returned a list fans out: each element is emitted as its own event into a fresh stream."） | `llamaindex_impl.py:165-167` |
| 并发上限 | `@step(num_workers=N)` | `workflows/decorators.py:126`；`workflows/runtime/types/internal_state.py:844`（"num_workers: Maximum number of concurrent executions of this step"）；调度见 `workflows/runtime/control_loop/reduce.py:526` | `llamaindex_impl.py:174` |
| 同步步体自动进线程池 | 引擎对非协程步体调 `run_in_executor(None, ...)` | `workflows/runtime/types/step_function.py:284-293` | `llamaindex_impl.py:175`（`def s_retrieve_one` 写成同步函数，不自己写线程池） |
| 事件归并 | `Context.collect_events(ev, expected, buffer_id=None)` | `workflows/context/context.py:446` | `llamaindex_impl.py:186` |
| 重试 | `@step(retry_policy=...)` + `retry_policy(retry=, wait=, stop=)` | `workflows/decorators.py:127`；`workflows/retry_policy.py:853`（组合工厂）、`:680`（`stop_after_attempt`）、`:212`（`retry_if_exception_type`）、`:453`（`wait_none`） | `llamaindex_impl.py:76,195` |
| 检查点 | `Context.to_dict(serializer=None, *, include_state=True)` | `workflows/context/context.py:357` | `llamaindex_impl.py:277` |
| 恢复 | `Context.from_dict(cls, workflow, data, serializer=None)` + `Workflow.run(ctx=...)` | `workflows/context/context.py:398`；`workflows/workflow.py:354`（`ctx` 是第一个位置参数） | `llamaindex_impl.py:293` |

**引擎的限制（不是本实现的取舍，是引擎行为，有源码依据）**：`Context.to_dict()` **只能从 handler 代码调用**，在步内调用抛 `ContextStateError: to_dict is only available from handler code, not from within steps.`（`workflows/context/context.py:391-395`）。

## 2. 复现步骤

### 2.1 环境

- WSL2 Ubuntu 24.04，内核 `6.18.33.2-microsoft-standard-WSL2`。
- 解释器 `/usr/bin/python3`（3.12.3）。
- `PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/llamaindex`（base 提供 rank_bm25/numpy，llamaindex 提供引擎；`runner.py` 自己把 `harness/` 目录插进 `sys.path`）。
- 无任何 LLM/API 凭据，全程离线本地进程。

### 2.2 依赖安装命令（逐字）

**本分片未额外安装任何包**（引擎与 rank_bm25 在实施前已就位）。环境提供方给出的安装命令原文如下（**本人未执行过这条命令**，此处按要求原样记录）：

```bash
python3 -m pip install --break-system-packages --target /home/ubuntu/dm/pylibs/llamaindex -i https://pypi.tuna.tsinghua.edu.cn/simple <pkg>
```

本分片实际执行过的全部 pip 安装命令条数：0。

### 2.3 复跑命令（逐字）

```bash
cd "$(git rev-parse --show-toplevel)"   # dsh-bounty 克隆根
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/llamaindex
python3 -X utf8 bench/cross_eval/harness/runner.py --impl bench/cross_eval/systems/llamaindex_impl.py --name llamaindex --modes normal,resume,retry,sequential,parallel 2>&1 | tee bench/cross_eval/raw/llamaindex_runner.txt
```

一行式（等价，供脚本内联）：

```bash
cd "$(git rev-parse --show-toplevel)"   # dsh-bounty 克隆根 && PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/llamaindex python3 -X utf8 bench/cross_eval/harness/runner.py --impl bench/cross_eval/systems/llamaindex_impl.py --name llamaindex --modes normal,resume,retry,sequential,parallel 2>&1 | tee bench/cross_eval/raw/llamaindex_runner.txt
```

### 2.4 预期耗时（实测，不是估算）

- 上面这条五模式复跑命令的墙钟耗时：**16.75 s**（`/usr/bin/time -f "WALL_SECONDS %e"` 实测，raw/llamaindex_walltime.txt）。其中每个模式各跑 1 次预热 + 7 次计时。
- 冷启动 import 占其中约 3 s（raw/llamaindex_coldimport.txt）。
- 只跑 normal 单模式约 4 s。

### 2.5 证据脚本（全部落在 `bench/cross_eval/raw/llamaindex_*`）

| 脚本 | 产出 | 用途 |
|---|---|---|
| `raw/llamaindex_run.sh` | `raw/llamaindex_runner.txt` 及 `raw/llamaindex_<mode>.txt` / `raw/llamaindex_out_<mode>.jsonl` / `raw/llamaindex_summary.json` | 五模式正式读数（§3、§4 M1/M4/M5/M6/M7） |
| `raw/llamaindex_walltime.sh` | `raw/llamaindex_walltime.txt` | 一轮五模式墙钟耗时（§2.4） |
| `raw/llamaindex_coldimport.py/.sh` | `raw/llamaindex_coldimport.txt` | M3 冷启动 import，基线与本方案交替各 5 次 |
| `raw/llamaindex_meta.py/.sh/.meta2.sh/.meta3.sh` | `raw/llamaindex_meta.txt` | M2/M3/M6/M8 读数与反伪造核对 |
| `raw/llamaindex_m7.py/.sh/.m7b.sh` | `raw/llamaindex_m7.txt` | M7 失败回溯原文 |
| `raw/llamaindex_m8.py/.sh` | `raw/llamaindex_m8.txt` | M8 du -sh / 版本 / 凭据扫描 / socket 封锁运行 |
| `raw/llamaindex_probe_module_registration.txt`、`raw/llamaindex_probe_module_registration_resume.txt` | 原始报错 | 实施期踩到的 `ImportError` 与修法（§4 M4 脚注） |

## 3. 基线 vs 方案对照读数

### 3.1 逐项对照表

| 读数项 | 基线（手写顺序 Python，`harness/baseline.py`） | 本方案（LlamaIndex Workflows） | 对照 |
|---|---|---|---|
| M1 产物 sha256 | `8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd`（match=True，40 行） | 同左，五模式全部 match=True | 逐字节一致 |
| M2 `metrics.loc` | 66 | 238 | 3.606× |
| M2 编排单元数（`@step`） | 0 | 7 | +7 |
| M3 冷启动 import（min–max，5 次） | 106.2–134.3 ms | 3006.7–3754.1 ms | min 倍率 28.312× |
| M3 normal min / p50 / p95 | 55.585 / 62.665 / 84.687 ms | 151.262 / 167.71 / 352.817 ms | min 2.721× / p50 2.676× / p95 4.166× |
| M3 sequential min / p50 / p95 | 46.087 / 54.883 / 73.168 ms | 170.63 / 182.175 / 219.3 ms | min 3.702× / p50 3.319× / p95 2.997× |
| M3 parallel min / p50 / p95 | 44.601 / 53.518 / 70.991 ms | 188.942 / 220.433 / 241.642 ms | min 4.236× / p50 4.119× / p95 3.404× |
| M4 恢复后重跑的步骤 | `["load","index","retrieve"]`（整段重跑） | `["verify","emit"]` | 本方案少重跑 load/index/retrieve |
| M4 恢复后各步执行计数 | 未提供（基线无计数表） | load=0 index=0 retrieve=0 verify=1 emit=1 | — |
| M5 真实尝试次数 | 3 | 3 | 相同数字，作用域不同（见 §0 第 6 条） |
| M6 parallel/sequential min 比 | 0.968 | 1.072 | 两家均无并行收益 |
| M7 失败错误文本 | `injected failure at verify` | `RuntimeError: injected failure at verify` | 两家都只含注入消息，都不由引擎点名步骤 |
| M8 依赖目录 du -sh | 共用 base 70M（无框架） | 247M（+ 共用 base 70M） | +247M |

### 3.2 原始输出片段（未改动任何数字）

以下为 `bench/cross_eval/raw/llamaindex_runner.txt` 原文片段：

```
IMPL bench/cross_eval/systems/llamaindex_impl.py NAME llamaindex
CAPS {"checkpoint": true, "fanout": true, "note": "checkpoint=Context.to_dict()/from_dict()（引擎限定只能从 handler 代码取，同进程内恢复；跨进程需自行持久化索引与 payload）；retry=@step(retry_policy=retry_policy(...))，作用域是单个 step 的单次执行；fanout=@step 返回 list[Event] + @step(num_workers=N)，同步步体由引擎自动 run_in_executor 放默认线程池", "retry": true}
RUN mode=normal ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
RUN mode=resume ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
FIRST_ERROR RuntimeError: injected failure at verify
REEXECUTED ["verify", "emit"]
RUN mode=retry ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
ATTEMPTS 3
ERROR_TEXT injected transient failure
RUN mode=sequential ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
RUN mode=parallel ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
TIMING normal {"min_ms": 151.262, "n": 7, "p50_ms": 167.71, "p95_ms": 352.817}
TIMING sequential {"min_ms": 170.63, "n": 7, "p50_ms": 182.175, "p95_ms": 219.3}
TIMING parallel {"min_ms": 188.942, "n": 7, "p50_ms": 220.433, "p95_ms": 241.642}
SUMMARY_WRITTEN raw/llamaindex_summary.json
```

以下为 `bench/cross_eval/raw/baseline_runner.txt` 原文片段（同一口径的基线读数）：

```
TIMING normal {"min_ms": 55.585, "n": 7, "p50_ms": 62.665, "p95_ms": 84.687}
TIMING sequential {"min_ms": 46.087, "n": 7, "p50_ms": 54.883, "p95_ms": 73.168}
TIMING parallel {"min_ms": 44.601, "n": 7, "p50_ms": 53.518, "p95_ms": 70.991}
```

### 3.3 三次独立运行的波动（同一脚本、同一机器）

| 运行 | normal min/p50/p95 | sequential min/p50/p95 | parallel min/p50/p95 |
|---|---|---|---|
| 正式落盘（raw/llamaindex_runner.txt） | 151.262 / 167.71 / 352.817 | 170.63 / 182.175 / 219.3 | 188.942 / 220.433 / 241.642 |
| 第二次（原始输出见 `raw/llamaindex_meta.txt` 的 M6 段同口径复测） | 184.727 / 272.451 / 469.729 | 144.709 / 165.033 / 218.945 | 160.92 / 174.397 / 189.576 |
| 第三次（raw/llamaindex_walltime.txt） | 283.601 / 313.823 / 452.878 | 176.003 / 234.117 / 346.811 | 197.391 / 211.381 / 286.579 |

三次都显示本方案各模式耗时高于基线同一量级（min 倍率约 2.7×–4.2×），但单次绝对值在 WSL2 上波动明显；§3.1 只采用正式落盘那一次，并保留本表供复跑者判断噪声量级。

## 4. 读数明细

### M1 产物 sha256 与基线是否逐字节一致 —— 一致

- 五模式 sha256 = `8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd`，`golden` 同值，`match=True`，`lines=40`（raw/llamaindex_runner.txt:4,7,12,16,19；逐模式文件 raw/llamaindex_normal.txt / _resume.txt / _retry.txt / _sequential.txt / _parallel.txt）。
- 实现细节（不影响 sha256，但复跑者需要知道）：并行扇出后 `s_gather` 用 `ctx.collect_events` 收齐 40 条 `RetrievedEv`，再**按 `idx` 升序还原查询顺序**（`llamaindex_impl.py:183-189`）。这是实现细节、不属于被考察能力；不做这步归并，emit 顺序会与黄金产物不一致。

### M2 非空非注释行数 + 编排单元数

- 工具：`harness/metrics.py` 的 `loc()`（源码原文：非空且不以 `#` 开头的行数，raw/llamaindex_meta.txt:2-10）。
- `loc llamaindex_impl.py = 238`；`loc baseline.py = 66`；`loc workload.py = 95`（raw/llamaindex_meta.txt:13-15）。
- 编排单元数：`@step 数（llamaindex_impl.py）= 7`；`@step 数（baseline.py）= 0`；另有 `class 定义 = 8`（raw/llamaindex_meta.txt:17-20）。
- 口径说明：Lead 口头给出的基线 LOC 是 44，本报告实测 `metrics.loc(baseline.py) = 66`（文件总行数 77）。差异来自统计口径（`loc` 只排除空行与 `#` 注释行）；本报告统一以 `metrics.loc` 为准。
- 反伪造核对（对 `llamaindex_impl.py` 文本计数，raw/llamaindex_meta.txt:22-29）：`ThreadPoolExecutor=0`、`asyncio.to_thread=0`、`Semaphore=0`、`concurrent.futures=0`、`while True=0`、`for _attempt=0`、`while attempt=0` —— 即本实现没有手写线程池/并发限流/重试循环；引擎 API 调用计数：`retry_policy=3`、`stop_after_attempt=1`、`num_workers=3`、`collect_events=1`、`to_dict=5`、`from_dict=5`。

### M3 冷启动 import 耗时 + 端到端 min/p50/p95

- 冷启动 import（交替各 5 次独立进程，raw/llamaindex_coldimport.txt）：基线 `[130.7, 134.3, 106.2, 119.1, 127.1]` ms；本方案 `[3754.1, 3006.7, 3251.3, 3329.7, 3242.5]` ms。min 106.2 vs 3006.7 ⇒ 28.312×。
- 另一次仅 import 引擎的实测：`engine_only_import_ms = 2202.5`（raw/llamaindex_meta.txt:37）。
- 端到端（`metrics.timeit`，repeats=7、warmup=1，raw/llamaindex_runner.txt:21-23）：normal `{"min_ms": 151.262, "n": 7, "p50_ms": 167.71, "p95_ms": 352.817}`；sequential `{"min_ms": 170.63, "n": 7, "p50_ms": 182.175, "p95_ms": 219.3}`；parallel `{"min_ms": 188.942, "n": 7, "p50_ms": 220.433, "p95_ms": 241.642}`。
- 基线同口径（raw/baseline_runner.txt:21-23）：normal `{"min_ms": 55.585, "n": 7, "p50_ms": 62.665, "p95_ms": 84.687}`；sequential `{"min_ms": 46.087, "n": 7, "p50_ms": 54.883, "p95_ms": 73.168}`；parallel `{"min_ms": 44.601, "n": 7, "p50_ms": 53.518, "p95_ms": 70.991}`。
- p95 口径说明：`cfg` 里没有重复次数参数，重复次数由 `runner.py --repeats`（默认 7）与 `metrics.timeit` 决定；基线与本方案用的是同一段代码、同一默认值，因此 §3.1 的 p95 是可比读数。

### M4 断点续跑：重跑了哪些步骤

- 注入点：`verify` 步入口抛 `RuntimeError("injected failure at verify")`。
- 恢复前计数：`{"emit": 0, "index": 1, "load": 1, "retrieve": 40, "verify": 3}`；恢复后计数：`{"emit": 1, "index": 0, "load": 0, "retrieve": 0, "verify": 1}`（raw/llamaindex_meta.txt:43）。
- 结论：`steps_reexecuted_after_failure = ["verify","emit"]`（raw/llamaindex_runner.txt:10）。load / index / retrieve **没有重跑**；基线同场景是 `["load","index","retrieve"]`（raw/baseline_runner.txt:10）。
- 名单来源：模块级计数表 `EXEC`（每个 step 入口 `_bump(name)`，`llamaindex_impl.py:86`）在失败前后各取一次快照做差，**不是硬编码**。用模块级而非局部变量，是因为局部变量会随重跑重置。
- 恢复载体与作用域：`handler.ctx.to_dict()`（`llamaindex_impl.py:277`）取 JSON 快照 → `Context.from_dict(flow2, data)`（`llamaindex_impl.py:293`）→ `await flow2.run(ctx=ctx2)` 续跑。作用域是**同一进程内**；跨进程重启恢复不在本读数覆盖范围内（§6）。
- 本实现自行添加的同步（**不属于引擎能力**）：因为引擎限定 `to_dict()` 只能从 handler 代码调用，本实现在 verify 步入口与 handler 之间加了两个 `asyncio.Event` 握手（handler 先取快照、再放行 verify 抛错）。这段握手是测评脚手架，引擎本身不提供"步内取快照"。
- 实施期踩到的坑（原始报错已落盘）：`runner.py:24-28` 用 `spec_from_file_location`+`exec_module` 加载实现模块但**不注册 `sys.modules`**，而 `Context.to_dict()` 把事件类序列化成"模块名.类名"、`Context.from_dict()` 再按该名 `import_module()` 反查（`workflows/context/serializers.py:192,215` → `workflows/context/utils.py:53`），于是首次 resume 直接 `ImportError: Failed to import module impl_llamaindex_impl: No module named 'impl_llamaindex_impl'`（raw/llamaindex_probe_module_registration.txt、raw/llamaindex_probe_module_registration_resume.txt）。修法：模块文件末尾把自身注册进 `sys.modules`（`llamaindex_impl.py` 末段）。这是实现侧适配，不是引擎缺陷。

### M5 重试真实尝试次数

- `ATTEMPTS 3`（raw/llamaindex_runner.txt:13），`ERROR_TEXT injected transient failure`（同文件 :14），产物 sha256 仍与黄金一致。
- 真实次数取自引擎账本 `ctx.retry_info().retry_number`（`workflows/context/context.py:588`），不是自建计数器；本实现内部 `EXEC["verify"] = 3` 与之一致。
- 作用域：`@step(retry_policy=_VERIFY_RETRY_POLICY)`（`llamaindex_impl.py:195`），`_VERIFY_RETRY_POLICY = retry_policy(retry=retry_if_exception_type(RuntimeError), wait=wait_none(), stop=stop_after_attempt(3))`（`llamaindex_impl.py:76`）⇒ 计的是 **verify 单个 step 的单次执行** 的尝试次数，不是整条 workflow 的重跑次数。基线的 3 是 `while` 循环里整步重试的次数（raw/baseline_runner.txt:13）。

### M6 并发 vs 串行耗时

- 正式落盘（raw/llamaindex_runner.txt:22-23）：sequential `{"min_ms": 170.63, "n": 7, "p50_ms": 182.175, "p95_ms": 219.3}`；parallel `{"min_ms": 188.942, "n": 7, "p50_ms": 220.433, "p95_ms": 241.642}`。
- 专项复测（raw/llamaindex_meta.txt:40-41，`metrics.timeit` repeats=7 warmup=1）：sequential `{"min_ms": 167.293, "n": 7, "p50_ms": 223.631, "p95_ms": 269.292}`；parallel `{"min_ms": 179.271, "n": 7, "p50_ms": 188.388, "p95_ms": 346.851}`。
- 比值（专项复测）：min 1.072、p50 0.842、p95 1.288；正式落盘那一次 min 比 1.107、p50 比 1.210。**没有任何一次显示并行比串行快。**
- 基线对照：parallel/sequential min 比 0.968、p50 比 0.975（raw/baseline_runner.txt:22-23）。
- 实现说明：扇出是引擎原生能力（`s_fanout` 返回 `list[QueryEv]`，`llamaindex_impl.py:165-167`）；并发上限是 `@step(num_workers=workers)`（`llamaindex_impl.py:174`，`workers=cfg["workers"]` 默认 4）；同步步体由引擎放进默认线程池（`workflows/runtime/types/step_function.py:284-293`），本实现没有写 `Semaphore`/`ThreadPoolExecutor`（raw/llamaindex_meta.txt:22-25）。
- 原因判断（只列与读数一致的机制，不做体验评价）：单条查询是对 200 篇文档的 BM25 打分，耗时极小；每条查询要过一遍"事件构造 → JSON 序列化 → 事件流投递 → 线程池调度 → 结果归并"，这部分固定开销大于被并行掉的检索时间。

### M7 失败时错误文本是否点名步骤 —— 不点名

- 注入失败后 `await handler` 抛出的是**原始** `RuntimeError`（`exc_module = builtins`），`str(exc) = 'injected failure at verify'`（raw/llamaindex_m7.txt）。其中 "verify" 来自注入消息本身，**不是引擎添加的步骤名**。
- 引擎在 `workflows/runtime/control_loop/runner.py:367` 处 `raise command.exception`，原样重抛，不做包装。
- 回溯中可定位到 step：`workflows/runtime/types/step_function.py:300` → `:233 span_safe_call` → `llamaindex_impl.py:203 in s_verify` → `RuntimeError`（raw/llamaindex_m7.txt 的 FULL_TRACEBACK 段）。
- 引擎确实自带"点名 step"的错误消息，但只出现在**类型校验/返回值校验**路径：`workflows/runtime/types/step_function.py:313` / `:328` / `:344` 的 f-string 形如 `Step function {step_name} returned a list ...`（`WorkflowRuntimeError`）。业务异常路径不包装。
- 基线对照：`FIRST_ERROR injected failure at verify`（raw/baseline_runner.txt:9），同样只含注入消息。

### M8 依赖足迹 du -sh + 零凭据可运行性

- `du -sh 70M /home/ubuntu/dm/pylibs/base`、`du -sh 247M /home/ubuntu/dm/pylibs/llamaindex`（raw/llamaindex_m8.txt；raw/llamaindex_meta.txt:47-48）。本方案相对基线多出的是 247M 的引擎依赖目录（其中包含 aiohttp / sqlalchemy / tiktoken / nltk / pillow 等传递依赖，见 raw/llamaindex_meta.txt:55-116）。
- 零凭据：扫描进程环境里含 `API_KEY/OPENAI/ANTHROPIC/TOKEN/SECRET/CREDENTIAL/PASSWORD` 的变量，`credential_like_env_count = 0`（raw/llamaindex_m8.txt）。
- 零网络：把 `socket.socket.connect` / `connect_ex` / `create_connection` 全部替换为抛错函数后跑 normal 全流程，结果 `normal ok=True n_results=40`、sha256 仍为 `8454e1f3...`、`network_connect_attempts = 0`（raw/llamaindex_m8.txt）。
- 本分片执行过的 pip 安装命令数：0。

## 5. 不适用条件

1. **需要跨进程/跨机器崩溃恢复的场景不适用。** 本方案的检查点载体是 `Context.to_dict()` 的 JSON 快照，作用域是同进程内；索引对象 `BM25Okapi` 不可 JSON 序列化，本实现把它放在进程内的 `ART[run_id]` 表里，跨进程必须自行持久化索引与事件 payload。依据：`workflows/context/context.py:357,398`；本分片实测的恢复是在同一进程内完成的（§4 M4）。
2. **单任务极短的负载不适用。** M6 三次读数都没有显示并行快于串行（parallel/sequential min 比 1.072 与 1.107，raw/llamaindex_meta.txt:40-41、raw/llamaindex_runner.txt:22-23）；这类负载上引入该引擎只增加固定开销。
3. **冷启动敏感的场景不适用。** CLI、短命进程、serverless 类用法下，冷启动 import 是 3006.7–3754.1 ms，对基线是 28.312×（raw/llamaindex_coldimport.txt）。
4. **相对基线的额外前置条件**：
   - 必须能安装并携带 247M 的隔离依赖目录（raw/llamaindex_m8.txt）；
   - 必须接受 `Context.to_dict()` 只能从 handler 代码调用的限制（`workflows/context/context.py:391-395`）；若要在步内取快照，需自行在 handler 与 step 之间搭同步（本实现用两个 `asyncio.Event`，属自行实现）；
   - `num_workers` 是装饰器参数，只能在建类时确定 ⇒ 运行时改变并发度需要重建工作流类（本实现按 `workers` 缓存工作流类，`llamaindex_impl.py:145`）；
   - 事件 payload 必须可 JSON 序列化（本实现把所有 payload 收成 JSON 字符串字段）；
   - 使用 `runner.py` 这类"按文件路径加载实现模块"的宿主时，实现模块必须自行注册 `sys.modules`，否则检查点恢复会 `ImportError`（§4 M4 脚注）。
5. **需要"引擎在异常文本里点名失败步骤"的排障方式时不适用。** M7 实测 `str(exc)` 不含引擎添加的步骤名，只能靠回溯帧定位（raw/llamaindex_m7.txt）。

## 6. 未测项与原因

1. **LLM 调用面未测。** 原因：本机进程内凭据类环境变量数 = 0（raw/llamaindex_m8.txt），且不允许联网调外部 API。因此该引擎的 LLM 相关能力（工具调用、消息归约、人工中断 `InputRequiredEvent` / `HumanResponseEvent` 等）本分片一律未测，报告中不给任何相关结论。
2. **网络能力未测。** 封死 socket 只证明了本五步流水线不发起网络连接（`network_connect_attempts = 0`），不能证明引擎的联网能力。
3. **分布式 / 多进程持久化后端未测。** 原因：未安装、未配置任何持久化后端；本分片只覆盖进程内 `Context` 序列化恢复。
4. **厂商托管服务未测。** 原因：同上（无凭据、禁止联网）。
5. **跨进程崩溃恢复未测。** 原因：需要进程外持久化后端，见 §5 第 1 条。
6. **负载规模外推未测。** 只测了 200 篇文档 / 40 条查询 / top-5 这一档；更大语料、更多查询下的并发收益与内存占用未测。
7. **与另外两家的横向排名未做。** 本分片只做"基线 vs 本方案"对照；三家之间的横比不在本分片范围。
8. **计时精度限制未消除。** WSL2 上同一脚本三次运行的 TIMING 波动明显（§3.3），本分片没有做 CPU pinning、也没有做多次交替取中位数；§3.1 采用正式落盘那一次，波动量级已如实列出。
9. **`resume` 模式的"未完成步骤"语义未做边界测试。** 只测了"verify 前注入一次失败"这一种注入点；在 fan-out 中途（部分 `QueryEv` 已完成）注入失败的恢复行为未测。
