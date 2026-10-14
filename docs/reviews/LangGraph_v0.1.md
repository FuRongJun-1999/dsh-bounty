# LangGraph 分片测评报告 v0.1

被测引擎：**LangGraph**（LangChain 官方图状态机）。本报告全部读数来自本机 WSL Ubuntu 24.04 的真实执行日志，
原始输出落在 `bench/cross_eval/raw/langgraph_*`。**零 LLM 判官**：全文不含任何模型评分或主观措辞，每条结论后括注读数编号或 `raw/<文件>`。

## 0. 结论摘要

1. **五模式全部成功，产物与黄金产物逐字节一致。** normal/resume/retry/sequential/parallel 五模式均 `ok=True`，输出文件 sha256 均为 `8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd`，与 `data/out_baseline.jsonl` 逐字节相同，40 行（M1；`raw/langgraph_runner.txt`）。
2. **断点续跑是引擎内建能力，且重跑范围比基线小。** verify 抛错后检查点停在 `next=('verify',)`，恢复只重跑 `verify` 一步，`load/index/retrieve` 直接复用检查点，`steps_reexecuted_after_failure=["verify"]`（M4；`raw/langgraph_runner.txt` 的 `REEXECUTED ["verify"]`）。同一场景下基线的返回值是 `["load","index","retrieve"]`，即整段重跑 3 步（M4；基线读数见 `raw/baseline_runner.txt`）。
3. **重试是引擎内建能力，真实尝试 3 次。** `RetryPolicy(max_attempts=3, retry_on=RuntimeError)`，返回 `ATTEMPTS 3`，verify 节点执行计数 `verify: 3`（M5；`raw/langgraph_runner.txt` 的 `ATTEMPTS 3` 与 `node_exec_counts`）。基线同样报 `ATTEMPTS 3`，但那是自写 `while` 循环而非引擎能力（M5；`raw/baseline_runner.txt`）。
4. **扇出没有可复现的耗时收益。** 交替 A/B 9 轮 p50：本方案 `parallel/sequential = 1.311`，即用 `Send` 扇出比本引擎自己的串行还慢（M6；`raw/langgraph_timing_ab.txt` 的 `AB_RATIO` 行）。第二轮独立复跑该比值为 1.268，方向一致；而并发度本身的收益（`max_concurrency=4 / 1`）在两轮里分别是 0.820 与 1.258，符号翻转，说明该量级已被机器噪声淹没（M6；`raw/langgraph_timing_ab.txt` 的 `AB_FANOUT` 行）。**结论是「无收益」，不是「慢 31%」。**
5. **编排代码量约为基线的 3.5 倍。** 本方案 231 非空非注释行，基线 66 行（M2；`raw/langgraph_runner.txt` 的 `LOC` 行）。
6. **冷启动有约 1.5–1.8 s 的额外 import 成本。** 独立子进程三次测得 1551.020 / 1493.923 / 1826.364 ms（M3；`raw/langgraph_runner.txt` 的 `COLD_START_IMPORT_MS` 行）。基线只用标准库 + `rank_bm25`，无此量级成本（M8；`raw/baseline_runner.txt` 无冷启动项）。
7. **依赖足迹 72M。** `/home/ubuntu/dm/pylibs/langgraph` 实测 `72M`（M8；`raw/langgraph_runner.txt` 的 `du -sh` 行）。
8. **两个引擎能力存在「默认不生效」陷阱，必须显式开启，否则整条路径不可用。** 默认 `JsonPlusSerializer(pickle_fallback=False)` 无法序列化状态里的 `BM25Okapi`，落检查点时抛 `TypeError: Type is not msgpack serializable: BM25Okapi`；默认 `default_retry_on` 对 `RuntimeError` 一律 `return False`，不显式传 `retry_on=RuntimeError` 则重试一次都不会发生（M8 依据；`raw/langgraph_runner.txt` 的「关键 API 依据」行，文件:行号见 §4 M8）。

## 1. 被测对象与版本

| 项 | 值 | 依据 |
|---|---|---|
| 引擎 | LangGraph（LangChain 官方图状态机） | — |
| langgraph | `1.2.15` | `/home/ubuntu/dm/pylibs/langgraph/langgraph-1.2.15.dist-info`（目录名读出） |
| langgraph-checkpoint | `4.3.0` | `/home/ubuntu/dm/pylibs/langgraph/langgraph_checkpoint-4.3.0.dist-info` |
| langchain-core | `1.6.10` | `/home/ubuntu/dm/pylibs/langgraph/langchain_core-1.6.10.dist-info` |
| 本方案实现 | `bench/cross_eval/systems/langgraph_impl.py`，`NAME="langgraph"` | 231 非空非注释行（M2） |
| 基线实现 | `bench/cross_eval/harness/baseline.py`，`NAME="baseline"` | 66 非空非注释行（M2） |
| 检索依赖 | `rank_bm25 0.2.2`、`numpy 2.5.4` | `/home/ubuntu/dm/pylibs/base/*.dist-info` |
| 解释器 | `/usr/bin/python3` = Python 3.12.3 | `raw/langgraph_runner.txt` 环境段 |
| 平台 | Linux DESKTOP-SR355KD 6.18.33.2-microsoft-standard-WSL2 x86_64 | 同上 |

**版本号说明**：以上版本字符串全部从 `*.dist-info` 目录名读取，不取自记忆。

**基线 LOC 口径不一致（如实记录）**：任务正文给出基线 LOC 44，但用 harness 自带的 `metrics.loc()` 实测 `bench/cross_eval/harness/baseline.py` 为 **66** 行非空非注释行（`raw/langgraph_runner.txt` 的 `LOC` 行）。本报告一律以 raw 实测的 66 为准；差异原因未查明（可能是正文用了更早的基线版本或不同的计数口径）。

## 2. 复现步骤

### 2.1 环境

- WSL Ubuntu 24.04（内核 `6.18.33.2-microsoft-standard-WSL2`），`/usr/bin/python3` = Python 3.12.3。
- 工作目录：dsh-bounty 克隆根（本次测量在 `/mnt/d/lingshu-memory-plugin/cross-eval-20261014`，Windows `D:\lingshu-memory-plugin\cross-eval-20261014`）。
- 环境变量：`PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/langgraph`。
- **无任何 LLM/API 凭据，全程不联网**：`env | grep -iE 'key|token|secret|api'` 输出为空（M8；`raw/langgraph_runner.txt` 凭据扫描段）。所有依赖来自本机目录。

### 2.2 依赖安装命令（逐字）

依赖由任务下发方预先装好，**本次测评未执行任何安装命令**。若需在等价环境重建，逐字命令为：

```bash
python3 -m pip install --break-system-packages --target /home/ubuntu/dm/pylibs/langgraph -i https://pypi.tuna.tsinghua.edu.cn/simple langgraph
```

### 2.3 复跑命令（逐字）

测评的全部读数由 `raw/langgraph_run.sh` 一键复现，脚本内容与逐字执行方式如下：

```bash
cd "$(git rev-parse --show-toplevel)"   # dsh-bounty 克隆根
bash bench/cross_eval/raw/langgraph_run.sh
```

脚本内部执行的核心命令（逐字，与任务书给定跑法一致）：

```bash
cd "$(git rev-parse --show-toplevel)"   # dsh-bounty 克隆根
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/langgraph
python3 -X utf8 bench/cross_eval/harness/runner.py --impl bench/cross_eval/systems/langgraph_impl.py --name langgraph --modes normal,resume,retry,sequential,parallel 2>&1 | tee bench/cross_eval/raw/langgraph_runner.txt
```

脚本另跑两个补充量：冷启动 import（独立子进程 3 次）与交替 A/B 计时（`bench/cross_eval/raw/langgraph_timing_ab.py`）。

### 2.4 预期耗时

- `runner.py` 五模式 + 三模式计时（7 次/模式，1 次预热）：约 **25–40 s**（本机实测）。
- 冷启动 import 3 次：约 **5 s**。
- 交替 A/B 计时（9 轮 × 4 组合 + 3 × 5 次扇出扫描）：约 **15–25 s**。
- 整脚本端到端：约 **1 分钟**（本机在与其他分片并行跑基准时曾观察到 2–3 分钟）。

## 3. 基线 vs 方案对照读数

### 3.1 逐项对照表

计时列优先采用**交替 A/B**（同一进程内 baseline 与 langgraph 轮流跑，满足 spec 的「计时交替进行」公平性规则，9 轮），来源 `raw/langgraph_timing_ab.txt`；
`runner.py` 自身的单次 TIMING 块（7 次）另列，来源 `raw/langgraph_runner.txt`。

| 读数 | 基线（baseline） | 本方案（langgraph） | 比值（本方案/基线） | 来源 |
|---|---|---|---|---|
| M1 产物 sha256 与黄金一致 | True（40 行） | True（40 行） | — | `raw/langgraph_runner.txt` / `raw/baseline_runner.txt` |
| M2 非空非注释行数 | 66 | 231 | 3.50× | `raw/langgraph_runner.txt` `LOC` 行 |
| M2 编排单元数（编译后图） | 无图结构（过程式函数） | 7 节点 / 6 边（linear）；8 节点 / 7 边（fanout） | — | `raw/langgraph_runner.txt` `GRAPH_LINEAR` / `GRAPH_FANOUT` 行 |
| M3 冷启动 import | 无第三方框架 import 项 | 1551.020 / 1493.923 / 1826.364 ms | — | `raw/langgraph_runner.txt` `COLD_START_IMPORT_MS` |
| M3 端到端 normal min/p50/p95 | 55.585 / 62.665 / 84.687 ms | 44.855 / 55.075 / 62.937 ms | 0.81 / 0.88 / 0.74 | `raw/langgraph_runner.txt` TIMING（两行分属两次 runner 调用） |
| M3 端到端 sequential（交替 A/B） | 38.813 / 51.986 / 117.964 ms | 48.651 / 58.419 / 139.976 ms | 1.25 / 1.12 / 1.19 | `raw/langgraph_timing_ab.txt` |
| M3 端到端 parallel（交替 A/B） | 44.972 / 65.431 / 176.839 ms | 53.241 / 76.573 / 167.262 ms | 1.18 / 1.17 / 0.95 | `raw/langgraph_timing_ab.txt` |
| M4 失败后重跑步骤 | `["load","index","retrieve"]`（整段，硬编码返回） | `["verify"]`（真实执行轨迹推导） | 3 步 → 1 步 | `raw/baseline_runner.txt` / `raw/langgraph_runner.txt` |
| M5 重试真实尝试次数 | 3（自写 while 循环） | 3（`RetryPolicy`，verify 执行计数 3） | — | 同上 |
| M6 并发 vs 串行耗时比 | 1.259（parallel/sequential，交替 A/B） | 1.311（parallel/sequential，交替 A/B） | 1.04 | `raw/langgraph_timing_ab.txt` |
| M7 错误文本点名步骤 | 未测（基线 resume 未落错误文本行） | `error_names_node=true`，文本含 `During task with name 'verify'` | — | `raw/langgraph_runner.txt` `LANGGRAPH_EVIDENCE mode=resume` |
| M8 依赖足迹 | 70M（`pylibs/base`） | 72M（`pylibs/langgraph`） | 1.03× | `raw/langgraph_runner.txt` `du -sh` 行 |
| M8 零凭据可运行 | True | True | — | `raw/langgraph_runner.txt` 凭据扫描段（空） |

### 3.2 原始输出片段（逐字，未改写任何数字）

以下围栏块内容直接摘自 `raw/langgraph_runner.txt`（本方案五模式与计时）：

```text
IMPL bench/cross_eval/systems/langgraph_impl.py NAME langgraph
RUN mode=normal ok=True
SHA 8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd golden=8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd match=True lines=40
TRACE ["load", "index", "retrieve", "verify", "emit"]
RUN mode=resume ok=True
FIRST_ERROR injected failure at verify
REEXECUTED ["verify"]
RUN mode=retry ok=True
ATTEMPTS 3
ERROR_TEXT injected transient failure
RUN mode=sequential ok=True
RUN mode=parallel ok=True
TIMING normal {"min_ms": 44.855, "n": 7, "p50_ms": 55.075, "p95_ms": 62.937}
TIMING sequential {"min_ms": 47.277, "n": 7, "p50_ms": 52.224, "p95_ms": 127.496}
TIMING parallel {"min_ms": 54.712, "n": 7, "p50_ms": 68.85, "p95_ms": 75.392}
```

以下围栏块内容直接摘自 `raw/langgraph_timing_ab.txt`（交替 A/B，基线/方案轮换）：

```text
AB_MODE=alternating rounds=9 workers=4 warmup=1
AB baseline sequential {"all_ms": [38.813, 43.525, 46.125, 51.867, 51.986, 68.004, 69.414, 72.68, 117.964], "min_ms": 38.813, "n": 9, "p50_ms": 51.986, "p95_ms": 117.964}
AB langgraph sequential {"all_ms": [48.651, 51.268, 52.498, 52.991, 58.419, 59.74, 63.617, 69.331, 139.976], "min_ms": 48.651, "n": 9, "p50_ms": 58.419, "p95_ms": 139.976}
AB baseline parallel   {"all_ms": [44.972, 51.058, 55.924, 58.772, 65.431, 75.697, 84.181, 124.202, 176.839], "min_ms": 44.972, "n": 9, "p50_ms": 65.431, "p95_ms": 176.839}
AB langgraph parallel   {"all_ms": [53.241, 67.821, 69.735, 75.266, 76.573, 79.207, 87.624, 97.506, 167.262], "min_ms": 53.241, "n": 9, "p50_ms": 76.573, "p95_ms": 167.262}
AB_RATIO baseline parallel/sequential p50 = 1.259
AB_RATIO langgraph parallel/sequential p50 = 1.311
AB_RATIO langgraph/baseline sequential p50 = 1.124
AB_RATIO langgraph/baseline parallel   p50 = 1.170
AB_FANOUT max_concurrency=1  {"min_ms": 56.776, "n": 5, "p50_ms": 64.695}
AB_FANOUT max_concurrency=4  {"min_ms": 70.294, "n": 5, "p50_ms": 81.394}
AB_FANOUT max_concurrency=40 {"min_ms": 71.438, "n": 5, "p50_ms": 91.942}
AB_FANOUT p50 ratio conc=4 / conc=1 = 1.258
```

### 3.3 读数波动声明

本机同时有其他分片在跑基准，`runner.py` 自身的单次 TIMING 块在两次独立整跑之间波动明显：同一 `normal` 模式曾读到 `p50_ms 91.887`（受争用）与 `55.075`（本次，见 `raw/langgraph_runner.txt`）；`sequential` 曾读到 `p50_ms 170.397 / p95_ms 644.38`。
因此 §3.1 表中跨引擎的计时对照一律采用**交替 A/B** 读数（同进程内轮换，9 轮），单次 TIMING 块只作本方案自身的参考。即便如此，M6 的扇出收益仍不可复现（见 §4 M6）。

## 4. 读数明细

### M1 产物 sha256 与基线是否逐字节一致

**是，逐字节一致。** 五模式输出 sha256 全部为 `8454e1f355832b516ed47eb3d479ffa14aa8f93bfbef30c2378b4bafb90940bd`，与黄金产物 `bench/cross_eval/data/out_baseline.jsonl` 相同，40 行。
`raw/langgraph_summary.json` 中五个模式的 `"matches_golden": true` 可逐条核对。
说明：五步全部调用 `harness/workload.py` 的纯函数（`step_load` / `step_index` / `step_retrieve` / `step_verify` / `step_emit`），检索算法四家共用，本实现未替换任何检索逻辑。

### M2 非空非注释行数 + 编排单元数

- **非空非注释行数**：`bench/cross_eval/systems/langgraph_impl.py` = **231**；基线 `bench/cross_eval/harness/baseline.py` = **66**（`raw/langgraph_runner.txt` `LOC` 行）。比值 3.50×。
- **编排单元数**（`metrics` 之外，由 impl 的 `__main__` 打印编译后图结构）：
  - linear 图：**7 节点 / 6 边**，`node_names=["__end__", "__start__", "emit", "index", "load", "retrieve", "verify"]`
  - fanout 图：**8 节点 / 7 边**，`node_names=["__end__", "__start__", "emit", "index", "load", "retrieve", "retrieve_one", "verify"]`
- **一次性构图耗时**：`COMPILE_LINEAR_MS 2.296`、`COMPILE_FANOUT_MS 6.788`（本次）；前两次整跑分别为 3.456 / 2.156 与 2.625 / 1.692。该开销与端到端分开量，且因为图在模块级编译一次、多次 `invoke` 复用，不计入稳态单次调用。

### M3 冷启动 import 耗时 + 端到端 min/p50/p95

- **冷启动 import**（独立子进程各测一次，量法：`/usr/bin/python3 -X utf8 -c` 导入 `langgraph_impl` 并计时，3 次）：
  `COLD_START_IMPORT_MS 1551.020` / `1493.923` / `1826.364`（`raw/langgraph_runner.txt`）。量法写进 `raw/langgraph_run.sh`，与端到端计时分开，未混在一段计时里。
- **端到端**（`metrics.timeit`，7 次，1 次预热，`raw/langgraph_runner.txt`）：
  - normal：`min 44.855 / p50 55.075 / p95 62.937 ms`
  - sequential：`min 47.277 / p50 52.224 / p95 127.496 ms`
  - parallel：`min 54.712 / p50 68.85 / p95 75.392 ms`
- **交替 A/B 端到端**（9 轮，`raw/langgraph_timing_ab.txt`）：
  - sequential：`min 48.651 / p50 58.419 / p95 139.976 ms`
  - parallel：`min 53.241 / p50 76.573 / p95 167.262 ms`

### M4 断点续跑重跑了哪些步骤

**只重跑 `verify`。** 真实执行轨迹（每节点自增执行计数，非硬编码）：

```text
LANGGRAPH_EVIDENCE mode=resume engine=InMemorySaver first_error="injected failure at verify" checkpoint_next_after_failure=["verify"] node_exec_counts={"emit": 1, "index": 1, "load": 1, "retrieve": 1, "verify": 2} steps_reexecuted_after_failure=["verify"] steps_reused_from_checkpoint=["load", "index", "retrieve"] error_names_node=true error_node_line="During task with name 'verify' and id '9e39981b-8cae-10ee-2600-fb50c6338bab'"
```

机制：图编译时挂 `InMemorySaver` 检查点；verify 抛错后 `app.get_state(cfg).next == ('verify',)`；再 `app.invoke(None, cfg)` 从检查点继续，`load/index/retrieve` 的执行计数保持 1（未重跑），`verify` 计数为 2（重跑 1 次）。
`steps_reexecuted_after_failure` 由「执行计数 > 1」推导得出，不是常量。

### M5 重试真实尝试次数

**3 次。** 机制：`add_node("verify", ..., retry_policy=RetryPolicy(max_attempts=3, retry_on=RuntimeError))`，verify 节点真实执行计数为 3。

```text
LANGGRAPH_EVIDENCE mode=retry engine=RetryPolicy(max_attempts=3,retry_on=RuntimeError) attempts=3 node_exec_counts={"emit": 1, "index": 1, "load": 1, "retrieve": 1, "verify": 3} retry_wall_ms=2908.459 trace=["load", "index", "retrieve", "verify", "emit"]
```

`attempts` 取自执行计数 `counts["verify"]`，非硬编码；`retry_wall_ms=2908.459` 是两次退避重试的实际墙钟开销（`RetryPolicy` 默认 `initial_interval=0.5`、`backoff_factor=2.0`、`jitter=True`）。

### M6 并发 vs 串行耗时

**扇出在 40 条查询这个量级上没有可复现的耗时收益。**

- 交替 A/B 9 轮 p50：`AB_RATIO langgraph parallel/sequential p50 = 1.311`；基线同口径 `= 1.259`（`raw/langgraph_timing_ab.txt`）。两者都 > 1，即两家的「并行」在本机都没有跑赢自己的串行。
- 独立复跑一次（同脚本，9 轮）：本方案 `parallel/sequential p50 = 1.268`，基线 `= 0.937`。方向部分一致（本方案两次都 > 1），但基线侧符号翻转。
- 并发度本身是否起作用（同一张 `Send` 图只改 `max_concurrency`，5 次取 p50）：本次 `conc=4/conc=1 = 1.258`（`64.695 → 81.394 ms`，即并发反而更慢）；上一轮为 `0.820`（`68.34 → 56.01 ms`，并发更快）。**符号翻转，说明该效应低于本机噪声底。**

扇出机制本身是引擎内建的（`Send` + `config["max_concurrency"]`，`langgraph/types.py:738`），确定性也成立（并发完成顺序不影响产物，sha 与黄金一致），但**耗时收益不可复现**，故不宣称任何加速。

### M7 失败时错误文本是否点名步骤

**点名了。** 错误文本含 `During task with name 'verify' and id '9e39981b-8cae-10ee-2600-fb50c6338bab'`，`error_names_node=true`（`raw/langgraph_runner.txt` 的 `LANGGRAPH_EVIDENCE mode=resume` 行）。
注意：原始 `RuntimeError` 的文本是 `injected failure at verify`（注入内容本身含步骤名），引擎额外附加的定位信息是 `During task with name 'verify' and id <task-uuid>` 这一层。
基线侧未测：`raw/baseline_runner.txt` 的 resume 模式只落了 `FIRST_ERROR injected failure at verify`，没有引擎附加的节点定位行，无法同口径对照，故基线该格标「未测」。

### M8 依赖足迹 + 零凭据可运行性

- **依赖足迹**：`du -sh /home/ubuntu/dm/pylibs/langgraph` = **72M**；对照 `du -sh /home/ubuntu/dm/pylibs/base` = **70M**（`raw/langgraph_runner.txt`）。
- **零凭据可运行性：成立。** 凭据扫描 `env | grep -iE 'key|token|secret|api'` 输出为空；全程未发起任何网络请求，五模式产物 sha256 与黄金一致。
- **关键 API 依据（文件:行号，`raw/langgraph_runner.txt` 原样落盘）**：

```text
122:        pickle_fallback: bool = False,
280:    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
1:def default_retry_on(exc: Exception) -> bool:
427:class RetryPolicy(NamedTuple):
738:class Send:
34:class InMemorySaver(
```

对应关系：`checkpoint` → `langgraph/checkpoint/memory/__init__.py:34`（`InMemorySaver`）+ `langgraph/checkpoint/serde/jsonplus.py:122/280`；`retry` → `langgraph/_internal/_retry.py:1`（`default_retry_on`）+ `langgraph/types.py:427`（`RetryPolicy`）；`fanout` → `langgraph/types.py:738`（`Send`）。

### CAPS 声明

```text
CAPS {"checkpoint": true, "fanout": true, "note": "checkpoint=InMemorySaver(serde=JsonPlusSerializer(pickle_fallback=True))（langgraph/checkpoint/memory/__init__.py；默认 pickle_fallback=False 见 langgraph/checkpoint/serde/jsonplus.py:122，默认 serde 无法序列化 BM25Okapi）；retry=RetryPolicy(retry_on=RuntimeError)（langgraph/types.py；默认 default_retry_on 对 RuntimeError 返回 False，见 langgraph/_internal/_retry.py）；fanout=Send+config[max_concurrency]（langgraph/types.py）", "retry": true}
```

三个能力均为**引擎内建**，无一是自写循环冒充：
- `checkpoint=true`：`InMemorySaver` 是 LangGraph 官方检查点后端，`app.get_state().next` / `app.invoke(None, cfg)` 续跑语义由引擎实现。
- `retry=true`：`RetryPolicy` 由引擎在节点执行层实施，节点函数内没有任何 `while`/`for` 重试代码。
- `fanout=true`：`Send` 由引擎的 `add_conditional_edges` 展开为并发任务，`max_concurrency` 由引擎调度器读取，未自建线程池。

## 5. 不适用条件

本方案的额外前置条件（相对基线而言）：

1. **必须能安装第三方依赖。** 需要 `langgraph 1.2.15` + `langgraph-checkpoint 4.3.0` + `langchain-core 1.6.10`，依赖足迹 72M，冷启动 import 1.5–1.8 s（M3/M8）。基线只用标准库 + 已有 `rank_bm25`，在无 pip / 无网络 / 磁盘受限的环境里仍可运行，本方案不能。
2. **检查点状态必须可序列化。** 引擎默认 serde 无法序列化 `BM25Okapi`，必须显式 `InMemorySaver(serde=JsonPlusSerializer(pickle_fallback=True))`；一旦换成不做 pickle 回退的持久化后端（或 `pickle_fallback=False`），本实现在落检查点时会直接抛 `TypeError: Type is not msgpack serializable: BM25Okapi` 而整条 resume 路径不可用。**本实现的检查点是进程内的**，进程退出即丢失，跨进程续跑不适用。
3. **重试必须显式声明 `retry_on`。** 默认 `default_retry_on` 对 `RuntimeError` 返回 `False`，不写 `retry_on=RuntimeError` 则一次重试都不会发生——若被重试的异常类型不是默认覆盖的类型，本实现的 retry 能力静默失效。
4. **扇出收益不适用于小任务量。** 40 条查询、单查询检索成本约亚毫秒级时，`Send` 的每任务编排开销超过并行节省（M6 两轮 A/B 均未见收益，且并发度收益符号翻转）。扇出只应在单任务成本显著大于编排开销时考虑；本报告**不提供**任何「扇出更快」的适用结论。
5. **检查点续跑的收益依赖失败点靠后。** 本方案失败在 verify（第 4 步）时才省下 3 步重跑（M4）；若失败发生在第 1 步 load，可复用的步骤为 0，此时相对基线的重跑优势消失。
6. **代码量成本。** 231 行 vs 基线 66 行（M2），且图编译有一次性开销（linear 2.296 ms / fanout 6.788 ms，本次），在一次性脚本场景下不划算。

## 6. 未测项与原因

| 未测项 | 原因 |
|---|---|
| LLM 调用面（节点内做模型推理、tool-calling、`create_react_agent` 等） | 本机**无任何 LLM/API 凭据**且不允许联网，无法构造真实模型调用；本测评的被测对象是确定性五步流水线，编排层不涉及模型。 |
| 网络相关能力（远程检查点后端、`langgraph-api` 服务化、跨机恢复） | 同上，环境不联网。 |
| 分布式 / 多进程持久化后端（`PostgresSaver` / `SqliteSaver` / 远程 checkpoint 服务） | 本机未安装这些后端的驱动，也未起数据库；`du -sh` 的 72M 只覆盖已装的 `langgraph` + `langgraph-checkpoint` 本地包。M8 的检查点结论**仅对 `InMemorySaver` 成立**。 |
| `resume` 跨进程续跑（进程退出后从磁盘检查点恢复） | 本实现用进程内 `InMemorySaver`，进程退出即丢失，无法测；这是实现选择而非引擎能力缺失。 |
| M7 的基线侧对照 | `raw/baseline_runner.txt` 未落引擎附加的节点定位文本，同口径不可比（见 §4 M7）。 |
| 高并发度下的正确性（`max_concurrency` > 40、多进程 worker） | 本轮只测了 `max_concurrency` = 1 / 4 / 40 三个点的耗时，且耗时已被噪声淹没；正确性只验证了 `workers=4` 下 sha 与黄金一致。 |
| 真实长任务（单查询检索成本显著高于编排开销）下的扇出收益 | 本工作负载单查询成本约亚毫秒级，无法外推到重负载；外推需要另一组语料/查询规模，超出本次分片范围。 |

**稳定性声明**：本报告所有读数均为本机（WSL2，同时有其他分片在跑基准）的单次会话观测。计时类读数（M3/M6）在两次独立整跑之间出现过显著漂移，已在 §3.3 与 §4 M6 逐处标注；正确性类读数（M1/M4/M5/M7）在三次整跑中完全一致。
