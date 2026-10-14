#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export http_proxy= https_proxy= all_proxy= HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= no_proxy=*
{
echo "### M8 零凭据/零联网复跑：显式置 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1，清空所有代理变量"
echo "### 环境变量："; env | grep -iE '^(HF_|TRANSFORMERS_|http_proxy|https_proxy|all_proxy|no_proxy)' | sort
echo "### 相关凭据变量（应为空）："; env | grep -iE 'API_KEY|TOKEN|SECRET|OPENAI|ANTHROPIC' || echo "(none)"
/usr/bin/python3 -X utf8 bench/cross_eval/harness/runner.py --impl bench/cross_eval/systems/txtai_impl.py --name txtai_offline --modes normal,resume,retry,sequential,parallel 2>&1 | grep -E '^(IMPL|CAPS|RUN|SHA|TRACE|ATTEMPTS|FIRST_ERROR|REEXECUTED|ERROR_TEXT|TIMING|ok|result)'
} 2>&1 | tee bench/cross_eval/raw/txtai_offline.txt
