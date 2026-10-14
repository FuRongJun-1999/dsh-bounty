#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
# LangGraph 分片：一键复跑脚本（第三方可原样执行）
# 用法：bash bench/cross_eval/raw/langgraph_run.sh（在克隆根下运行）
# 说明：本脚本只读 harness/ 与 data/，只写 raw/langgraph_*；不联网、不调用任何 LLM API。
set -u
cd "$ROOT"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/langgraph
export PYTHONDONTWRITEBYTECODE=1

echo "########## [1/7] 运行环境 ##########"
uname -a
echo "python: $(/usr/bin/python3 -V 2>&1)"
echo "--- langgraph 侧 dist-info ---"
ls -d /home/ubuntu/dm/pylibs/langgraph/langgraph-*.dist-info /home/ubuntu/dm/pylibs/langgraph/langgraph_checkpoint-*.dist-info /home/ubuntu/dm/pylibs/langgraph/langchain_core-*.dist-info
echo "--- base 侧 dist-info ---"
ls -d /home/ubuntu/dm/pylibs/base/*.dist-info

echo "########## [2/7] 五模式统一跑法（runner.py，落 raw/langgraph_*） ##########"
/usr/bin/python3 -X utf8 bench/cross_eval/harness/runner.py \
  --impl bench/cross_eval/systems/langgraph_impl.py \
  --name langgraph \
  --modes normal,resume,retry,sequential,parallel 2>&1 | tee bench/cross_eval/raw/langgraph_runner.txt

echo "########## [3/7] M3 冷启动 import（独立子进程，3 次） ##########"
for i in 1 2 3; do
  /usr/bin/python3 -X utf8 -c "import sys,time; sys.path.insert(0,'$ROOT/bench/cross_eval/systems'); t=time.perf_counter(); import langgraph_impl; print('COLD_START_IMPORT_MS %.3f' % ((time.perf_counter()-t)*1000.0))"
done

echo "########## [3b/7] M6 交替 A/B 计时（基线/方案轮换，spec 公平性规则） ##########"
# 该脚本自己写 raw/langgraph_timing_ab.txt，不要再 tee（会与脚本自身的写入互相覆盖，产出半行重复）
/usr/bin/python3 -X utf8 bench/cross_eval/raw/langgraph_timing_ab.py 2>&1

echo "########## [4/7] M2 编排单元数（编译后图结构）+ 一次性构图耗时 ##########"
cd "$ROOT/bench/cross_eval/systems"
/usr/bin/python3 -X utf8 langgraph_impl.py
cd "$ROOT"

echo "########## [5/7] M2 非空非注释行数 ##########"
/usr/bin/python3 -X utf8 -c "
import sys; sys.path.insert(0,'$ROOT/bench/cross_eval/harness')
import metrics
for p in ['bench/cross_eval/harness/baseline.py','bench/cross_eval/systems/langgraph_impl.py']:
    print('LOC %-46s %d' % (p, metrics.loc(p)))
"

echo "########## [6/7] M8 依赖足迹 + 零凭据 + 关键 API 依据 ##########"
du -sh /home/ubuntu/dm/pylibs/langgraph /home/ubuntu/dm/pylibs/base
echo "---- 凭据环境变量扫描（期望为空） ----"
env | grep -iE 'key|token|secret|api' || echo "(empty: 无任何 LLM/API 凭据)"
echo "---- 关键 API 依据（文件:行号） ----"
grep -n 'pickle_fallback: bool = False' /home/ubuntu/dm/pylibs/langgraph/langgraph/checkpoint/serde/jsonplus.py
grep -n 'def dumps_typed' /home/ubuntu/dm/pylibs/langgraph/langgraph/checkpoint/serde/jsonplus.py
grep -n 'def default_retry_on' /home/ubuntu/dm/pylibs/langgraph/langgraph/_internal/_retry.py
grep -n '^class RetryPolicy\|^class Send' /home/ubuntu/dm/pylibs/langgraph/langgraph/types.py
grep -n 'class InMemorySaver' /home/ubuntu/dm/pylibs/langgraph/langgraph/checkpoint/memory/__init__.py

echo "########## [7/7] 证据行 ##########"
grep -n 'LANGGRAPH_EVIDENCE' bench/cross_eval/raw/langgraph_runner.txt
