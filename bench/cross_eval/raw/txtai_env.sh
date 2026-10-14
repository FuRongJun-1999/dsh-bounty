#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
{
echo "=== date ==="; date -Is
echo "=== os ==="; . /etc/os-release; echo "$PRETTY_NAME"; uname -r
echo "=== python ==="; /usr/bin/python3 -V
echo "=== cpu/mem ==="; nproc; grep MemTotal /proc/meminfo
echo "=== uid ==="; id -u
echo "=== sudo -n true ==="; sudo -n true 2>&1 | head -3
echo "=== txtai version ==="; /usr/bin/python3 -X utf8 -c "import txtai,sys;print(txtai.__version__)"
echo "=== dist-info ==="; ls -d /home/ubuntu/dm/pylibs/txtai/*.dist-info
} 2>&1 | tee bench/cross_eval/raw/txtai_env.txt
