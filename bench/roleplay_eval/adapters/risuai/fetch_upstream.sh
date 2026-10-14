#!/usr/bin/env bash
# 取 RisuAI 上游源码到 adapters/risuai/upstream/。
# upstream/ 不进版本库：本脚本可随时重建该目录。
# 用 codeload 直连（GitHub 的 git clone 在本机常被重置）。
set -euo pipefail

OWNER_REPO="kwaroran/Risuai"
SHA="454e5e207747399f43a4788f5f08ecd5aa291550"
# package.json 的 git blob sha1，取自上游 API contents?ref=<SHA>；用于校验确实拿到该快照。
PKG_BLOB="eeb47ce1606584e68265ef4e823873b6ee5951c0"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${HERE}/upstream"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

URL="https://codeload.github.com/${OWNER_REPO}/tar.gz/${SHA}"
echo "FETCH start url=${URL} dest=adapters/risuai/upstream"
curl -sSL --retry 5 --retry-delay 3 --max-time 600 -o "${TMP}/src.tgz" "${URL}"
echo "FETCH downloaded bytes=$(wc -c < "${TMP}/src.tgz")"

rm -rf "${DEST}"
mkdir -p "${DEST}"
tar xzf "${TMP}/src.tgz" -C "${DEST}" --strip-components=1

python -X utf8 - "${DEST}/package.json" "${PKG_BLOB}" <<'PY'
import hashlib, sys, pathlib
p = pathlib.Path(sys.argv[1]); want = sys.argv[2]
b = p.read_bytes()
got = hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()
if got != want:
    raise SystemExit("FETCH blob-mismatch package.json got=%s want=%s" % (got, want))
print("FETCH blob-ok package.json %s" % got)
PY

echo "FETCH ok commit=${SHA} files=$(find "${DEST}" -type f | wc -l)"
