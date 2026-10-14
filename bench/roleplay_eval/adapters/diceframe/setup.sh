#!/usr/bin/env bash
# 建 venv 并装 diceframe 依赖（Tsinghua 镜像）。运行期不需要网络与凭据。
# 用法：bash setup.sh [源码目录]（默认 adapters/diceframe/upstream）
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPSTREAM="${1:-$HERE/upstream}"
VENV="$HERE/.venv"
MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
PYTHON="${PYTHON:-python}"

if [ ! -f "$UPSTREAM/requirements.txt" ]; then
  echo "缺少 $UPSTREAM/requirements.txt；先跑 bash $HERE/fetch_upstream.sh" >&2
  exit 2
fi

"$PYTHON" -m venv "$VENV"
PY="$VENV/Scripts/python.exe"
[ -x "$PY" ] || PY="$VENV/bin/python"

"$PY" -m pip install -i "$MIRROR" -r "$UPSTREAM/requirements.txt" "pytest>=8,<10" "pytest-asyncio>=0.24,<2"
"$PY" -c "import sys; print('python', sys.version.split()[0])"
echo "OK venv -> $VENV"
echo "用法：$PY bench/roleplay_eval/harness/runner.py --adapter diceframe --profiles P0,P1,P2,P3,P4"
