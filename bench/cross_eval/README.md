# cross-eval 基准：智能体工作流方向（v0.1）

本目录是悬赏委托 **cross-eval（横向测评）** 的交付实现与原始证据：同一台机器、同一份语料与查询、同一 BM25 实现下，
对三个「智能体工作流」方案与一份手写基线做逐项对照读数。测评方法论与三份方案报告在 `docs/reviews/`。

被测对象（与首轮交付的「记忆系统」方向完全不相交）：

| 名称 | 版本 | 实现 |
|---|---|---|
| 基线（手写） | — | `harness/baseline.py` |
| LangGraph | 1.2.15 | `systems/langgraph_impl.py` |
| LlamaIndex Workflows | llama-index-core 0.14.25 / llama-index-workflows 2.26.0 | `systems/llamaindex_impl.py` |
| txtai Workflow | 8.x（见报告 §1） | `systems/txtai_impl.py` |

## 目录

- `harness/spec.md` —— 冻结的评测契约（方向 / 被测对象 / 工作负载 / 读数项 M1–M8 / 公平性 / 未测面）
- `harness/workload.py` —— **唯一的工作负载定义**：五步流水线 `load → index → retrieve → verify → emit`，四家共用同一份纯函数
- `harness/metrics.py` —— `sha256_file` / `loc`（非空非注释行）/ `timeit`（1 次预热 + 7 次取样，报 min/p50/p95）
- `harness/baseline.py` —— 手写基线（ThreadPoolExecutor 扇出；无检查点、无内建重试）
- `harness/runner.py` —— 统一跑法（`--impl --name --modes --corpus --queries --rawdir --workers --repeats`），自动落 `raw/`；
  模式异常或 `ok` 非真 ⇒ 进程**非零退出**（打印 `FAILED modes=…`），且引擎自报证据键**全量**并入
  `raw/<name>_summary.json` 与 `raw/<name>_<mode>.txt` 的 `REC` 行（不可序列化键名记在 `dropped_keys`）
- `data/` —— 语料 200 篇（种子 20261014）、查询 40 条（种子 20261015）、黄金产物 `out_baseline.jsonl`
- `systems/` —— 三家方案实现，每个暴露 `NAME` / `CAPS` / `run(mode, cfg)`
- `raw/` —— **原始证据**（逐模式 stdout、逐模式产物 jsonl、summary json、计时日志、复跑脚本）

## 复跑

环境：Linux/WSL + `python3` 3.12，`nproc` 4 以上，**不需要任何 LLM/API 凭据**（工作负载纯本地、无网络）。
依赖装在隔离目录，避免互相污染：

```sh
python3 -m pip install --break-system-packages --target ~/dm/pylibs/base       rank_bm25
python3 -m pip install --break-system-packages --target ~/dm/pylibs/langgraph  langgraph
python3 -m pip install --break-system-packages --target ~/dm/pylibs/llamaindex llama-index-core
python3 -m pip install --break-system-packages --target ~/dm/pylibs/txtai      txtai
```

复跑（在仓根执行；`<name>` 取 `baseline` / `langgraph` / `llamaindex` / `txtai`）：

```sh
cd <repo>
export PYTHONPATH=~/dm/pylibs/base:~/dm/pylibs/<target>
python3 -X utf8 bench/cross_eval/harness/runner.py --impl bench/cross_eval/harness/baseline.py \
    --name baseline --modes normal,resume,retry,sequential,parallel
```

预期耗时：基线整轮（5 模式 + 3 组计时）约 1 分钟内；三家首轮含冷启动 import，约 1–3 分钟（txtai 首次 import 可达 30 s）。
`runner.py` 会打印 `SHA … golden=… match=…`、`TRACE`、`ATTEMPTS`、`TIMING`，并把原始文本写进 `raw/`。

## 守卫与 CI

```sh
python3 -X utf8 scripts/check_reviews.py        # 14 条交付物判据，退出码 0 全绿
python3 -X utf8 tests/test_check_reviews.py     # 正向 1 条 + 29 条定点变异 + 判据面/点名自证
```

`scripts/check_reviews.py` 的 14 条判据：交付文件齐备（R1）、报告七个固定二级标题逐字且有序（R2）、
方法论九节齐备（R3）、引用的 `raw/<文件>` 真实存在（R4）、围栏里的读数行能在**该报告自己的证据桶**里
逐字指到（R5，跨引擎引用需在围栏紧邻上方点名 `raw/<文件>`）、
无判官词（R6）、复现命令在位（R7）、声称与证据一致（R8，逐模式 **fail-closed**：模式记录缺 64 位
十六进制 sha256 指纹、`matches_golden` 非布尔，或为 false 而报告未在同一行披露 ⇒ 判红）、
黄金产物 sha256 在方法论正文里（R9）、
未测项非空（R10）、不适用条件非空（R11）、结论逐项可指（R12）、
**声称出处与证据一致（R13：`raw/<文件>` 引用所在行的标识符型读数 token 必须真在该文件里；
如实写「未落盘」的 token 豁免）**、
**正文（围栏之外）的读数行与 64 位摘要同样逐字可指（R14）**。

R7/R10/R11/R12 的节切分是**结构化**的（`section_body_ex()`）：按行切出**正文区**（围栏之外）的二级标题，
只认与目标标题**逐字相等且唯一**的那一节，切尾边界也只在正文区里找。标题出现 0 次或 ≥2 次
（含埋在围栏里的假头、重复标题）⇒ 该条判红并**在 `--quiet` 下打 `NOTE` 点名**——重复标题本身就是
报告结构缺陷，不许「取首次出现」蒙过去。围栏块（R5）／正文（R9）／节切分共用同一份围栏状态机 `scan_lines()`。
CI 在 `.github/workflows/review-cross-eval-check.yml`：守卫 + 自证 + 「跑完不许把仓搞脏」。

## 口径与边界

- `raw/*.txt` / `raw/*.json` / `raw/*.jsonl` 是**原始日志（证据）**，其中出现的绝对路径属于测量机，未做改写；
  `raw/*.sh` / `raw/*.py` 用 `$(dirname "$0")/../../..` 或 `__file__` 自行定位克隆根，可直接复跑。
- **证据桶按归属切分**（R5/R13/R14 的核对面）：`<引擎>_*` 的 `.txt/.json/.jsonl` 是该引擎报告自己的证据桶，
  `raw/*.sh` / `raw/*.py` **不是**读数证据面（源码行不能给报告背书）；跨引擎引用（如引用
  `baseline_runner.txt` 的对照读数）必须在围栏**紧邻上方**点名 `raw/<文件>`，且该行必须真在
  那份文件里逐字存在——点名了却不 owning，一样判红。
- 报告里**声称未落盘**的读数豁免 R13：如实声明不落盘不算编造，但声明之外仍声称「见 raw/<文件>」
  的 token 必须真在那份文件里。现行声明在 LangGraph 报告 **§4（读数明细）末尾**的「证据未落盘清单」
  （7 项由终端打印、未随仓落盘；§5 末尾另有一句平实语言的落盘边界说明）——清单与要它解释的读数同节，
  且不与 §5/§6 的结论性段落耦合（清了 §5 不会连带删掉这份声明）。
- 本基准只测**离线、公开可得、零凭据**的工作负载；不测厂商托管服务，不采集隐私数据。
- 并发耗时在 CPU 密集负载下受 GIL 限制，**不作为引擎优劣判据**；详见方法论 §5 与各家报告 §5「不适用条件」。
- 未测面（LLM 调用面、网络、分布式持久化后端、跨进程恢复等）逐家写在报告 §6「未测项与原因」。
