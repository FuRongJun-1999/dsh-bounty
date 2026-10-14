#!/usr/bin/env bash
# 取 SillyTavern 源码快照到 adapters/sillytavern/upstream/（只读快照，不进版本库；本脚本可重建该目录）。
# GitHub 直连 git clone 常被重置，故走 codeload 压缩包。
# 用法：bash fetch_upstream.sh
set -euo pipefail

OWNER_REPO="SillyTavern/SillyTavern"
SHA="06bde939fb1e9c4c8d8641d810f0a916b5bce127"
WANT_VERSION="1.19.0"
# spike/st-roleplay/SPIKE.md §1 记录的同 sha 压缩包摘要。不一致只打印 WARN，不中止。
KNOWN_TGZ="d3c5b32e7a1b649366d7d35eaaf877b06376864aacd8713ee8e670ff8ee4099c"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${HERE}/upstream"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

URL="https://codeload.github.com/${OWNER_REPO}/tar.gz/${SHA}"
echo "FETCH start url=${URL} dest=adapters/sillytavern/upstream"
curl -sSL --retry 5 --retry-delay 3 --max-time 600 -o "${TMP}/src.tgz" "${URL}"
echo "FETCH downloaded bytes=$(wc -c < "${TMP}/src.tgz")"
GOT_TGZ="$(sha256sum "${TMP}/src.tgz" | cut -d' ' -f1)"
echo "FETCH tarball_sha256=${GOT_TGZ}"
if [ "${GOT_TGZ}" != "${KNOWN_TGZ}" ]; then
  echo "WARN tarball_sha256 与 SPIKE.md 记录不同；git 归档的 gzip 层可随打包变化，内容校验以下一步为准"
fi

# 目录校验：只删本适配器目录下的 upstream。
if [ "${DEST}" != "${HERE}/upstream" ]; then
  echo "REFUSE 目标目录不是 ${HERE}/upstream" >&2
  exit 2
fi
rm -rf "${DEST}"
mkdir -p "${DEST}"
tar xzf "${TMP}/src.tgz" -C "${DEST}" --strip-components=1

VERSION="$(python -X utf8 -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8'))['version'])" "${DEST}/package.json")"
if [ "${VERSION}" != "${WANT_VERSION}" ]; then
  echo "FAIL package.json version=${VERSION} want=${WANT_VERSION}" >&2
  exit 3
fi
echo "FETCH version-ok package.json ${VERSION}"
echo "FETCH ok commit=${SHA} files=$(find "${DEST}" -type f | wc -l)"
