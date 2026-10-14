#!/usr/bin/env bash
# 取 diceframe 源码快照到 adapters/diceframe/upstream/（只读快照，不进版本库）。
# 用法：bash fetch_upstream.sh [目标目录]
set -euo pipefail

SHA=d2246e0d0d32867e8e090c238b588441bad96a28
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:-$HERE/upstream}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# GitHub 直连 git clone 常被重置，故走 codeload 压缩包。
curl -sSL -o "$TMP/src.tgz" "https://codeload.github.com/diceframe/diceframe/tar.gz/$SHA"
mkdir -p "$DEST"
tar xzf "$TMP/src.tgz" -C "$DEST" --strip-components=1
echo "OK diceframe $SHA -> $DEST"
