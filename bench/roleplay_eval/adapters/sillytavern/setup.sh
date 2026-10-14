#!/usr/bin/env bash
# 装 SillyTavern 运行依赖（npm ci）与 tests 依赖（npm install，含 @playwright/test）。
# 运行期零网络零凭据：本脚本只在安装期取 npm 公开源。
# 用法：bash setup.sh [源码目录]（默认 adapters/sillytavern/upstream）
#
# 浏览器：默认跑 `npx playwright install chromium`。
#   本机实测该命令在解压阶段挂死（2/2 复现，证据 spike/st-roleplay/SPIKE.md §4.3）。
#   绕过办法：设 CHROME_PATH 指向已装 chrome，本脚本据此跳过下载；run.mjs 也读该变量。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPSTREAM="${1:-${HERE}/upstream}"
NODE_BIN="${NODE_BIN:-node}"
NPM_BIN="${NPM_BIN:-npm}"

if [ ! -f "${UPSTREAM}/package.json" ]; then
  echo "缺少 ${UPSTREAM}/package.json；先跑 bash ${HERE}/fetch_upstream.sh" >&2
  exit 2
fi

echo "SETUP node=$("${NODE_BIN}" --version) npm=$("${NPM_BIN}" --version)"
cd "${UPSTREAM}"
echo "SETUP start npm ci"
"${NPM_BIN}" ci --no-audit --no-fund
echo "SETUP node_modules_bytes=$(du -sb node_modules | cut -f1) files=$(find node_modules -type f | wc -l)"

cd "${UPSTREAM}/tests"
echo "SETUP start npm install (tests)"
"${NPM_BIN}" install --no-audit --no-fund
echo "SETUP tests_node_modules_bytes=$(du -sb node_modules | cut -f1) files=$(find node_modules -type f | wc -l)"

if [ -n "${CHROME_PATH:-}" ]; then
  if [ ! -x "${CHROME_PATH}" ]; then
    echo "FAIL CHROME_PATH 不存在或不可执行：${CHROME_PATH}" >&2
    exit 3
  fi
  echo "SETUP browser=CHROME_PATH ${CHROME_PATH} 跳过 npx playwright install chromium"
else
  echo "SETUP start npx playwright install chromium"
  npx playwright install chromium
  echo "SETUP browser=playwright-default"
fi
echo "SETUP ok"
