#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
set -u
cd "$ROOT"/bench/cross_eval/raw
# 先固化「未注册 sys.modules 时 resume 失败」的原始证据，再重跑
cp -f llamaindex_runner.txt llamaindex_probe_module_registration.txt
cp -f llamaindex_resume.txt llamaindex_probe_module_registration_resume.txt
ls -la llamaindex_probe_module_registration*.txt
