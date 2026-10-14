#!/usr/bin/env bash
# 装被测方依赖。npm 走不通（@tauri-apps/cli-win32-arm64-msvc 写在 dependencies，EBADPLATFORM），
# 改用仓库 packageManager 字段锁定的 pnpm。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${HERE}/upstream"
echo "SETUP start npx --yes pnpm@10.34.1 install --frozen-lockfile"
npx --yes pnpm@10.34.1 install --frozen-lockfile
echo "SETUP ok node_modules_bytes=$(du -sb node_modules | cut -f1) node_modules_files=$(find node_modules -type f | wc -l)"
