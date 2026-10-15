#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""链接校验器（悬赏 #71 交付件）：扫描目录内 Markdown 的全部外链，逐条验活。

用法：
    python -X utf8 scripts/check_links.py docs/promo/           # 正常校验，期望退出码 0
    python -X utf8 scripts/check_links.py docs/promo/ --mutate  # 定点变异自证

守卫（断言）清单——任一不过即点名并退出 1：
    G1 数量守卫：去重后链接总数 ≥ 3（渠道面下限）。
    G2 协议守卫：每条链接必须以 https:// 开头。
    G3 占位守卫：禁止占位主机/片段（example.com / localhost / TODO / xxx），
       占位链接不构成发布。
    G4 可达守卫：每条链接 HTTP 状态须为 200–399（逐条点名失败者）。
    G5 深链守卫：每条链接须指向具体页面（路径长度 > 1）；站点根
       （如 https://github.com 本身）不是实际发布位置，不构成交付
       （对应维护者对在办提案的裁决点 (a)）。

定点变异自证（--mutate）：取扫描到的第一条（排序后）链接，人为改坏其
路径（追加 /__mutated_404__），对变异后的集合重跑全部守卫；期望——校验
必红且输出点名该变异链接。若变异未被抓到，自证失败，退出 1。

退出码：0 = 全部通过（或变异自证成立）；1 = 有守卫/链接失败；
        2 = 入参错误（目录不存在、无 Markdown、无链接可验）。
纯标准库；网络请求带浏览器 UA（某些出网代理会拒绝默认 UA）。
"""
from __future__ import annotations

import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

URL_RE = re.compile(r"https?://[^\s\)\]\>\"'`，。；：、]+")
PLACEHOLDER_MARKERS = ("example.com", "example.org", "example.net",
                       "localhost", "127.0.0.1", "todo", "xxx")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TIMEOUT = 25


def extract_urls(paths):
    urls = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for raw in URL_RE.findall(text):
            urls.append(raw.rstrip(".,`"))
    return urls


def probe(url):
    """返回 (可达, 说明)。先 HEAD，405/501 时回退 GET。"""
    safe = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")
    last = "unreachable"
    for attempt in range(3):
        for method in ("HEAD", "GET"):
            req = urllib.request.Request(safe, method=method,
                                         headers={"User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    return 200 <= resp.status < 400, "HTTP %d" % resp.status
            except urllib.error.HTTPError as exc:
                if exc.code in (405, 501) and method == "HEAD":
                    continue
                last = "HTTP %d" % exc.code
                if exc.code in (429, 503) and attempt < 2:
                    break  # 限流：退避后整轮重试一次
                return False, last
            except Exception as exc:  # DNS / TLS / 超时等一律判不可达并点名
                return False, "%s: %s" % (type(exc).__name__, exc)
        time.sleep(5)
    return False, last


def run_guards(urls, check_reachability=True):
    """跑全部守卫，返回失败清单（每条点名）。空清单＝全过。"""
    failures = []
    unique = set(urls)
    # G1 数量守卫
    if len(unique) < 3:
        failures.append("[G1 数量守卫] 去重后链接仅 %d 条 < 3" % len(unique))
    for url in sorted(unique):
        # G2 协议守卫
        if not url.startswith("https://"):
            failures.append("[G2 协议守卫] 非 https 链接：%s" % url)
        # G3 占位守卫
        low = url.lower()
        if any(marker in low for marker in PLACEHOLDER_MARKERS):
            failures.append("[G3 占位守卫] 占位链接：%s" % url)
        # G5 深链守卫
        if len(urllib.parse.urlsplit(url).path) <= 1:
            failures.append("[G5 深链守卫] 链接为站点根、非具体发布页：%s" % url)
    if check_reachability:
        # G4 可达守卫
        for url in sorted(unique):
            ok, why = probe(url)
            print("  %s %s  %s" % ("✓" if ok else "✗", why, url))
            if not ok:
                failures.append("[G4 可达守卫] 链接不可达（%s）：%s" % (why, url))
    return failures


def mutate_first(urls):
    """把第一条（排序后）链接的路径改坏，返回 (变异链接, 变异后集合)。"""
    target = sorted(set(urls))[0]
    parts = urllib.parse.urlsplit(target)
    broken = urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path + "/__mutated_404__",
         parts.query, parts.fragment))
    mutated = [broken if u == target else u for u in urls]
    return broken, mutated


def main(argv):
    args = [a for a in argv if a != "--mutate"]
    mutate = "--mutate" in argv
    if len(args) != 1:
        print("用法：python -X utf8 scripts/check_links.py <目录> [--mutate]")
        return 2
    root = Path(args[0])
    if not root.is_dir():
        print("✗ 目录不存在：%s" % root)
        return 2
    md_files = sorted(root.rglob("*.md"))
    if not md_files:
        print("✗ 目录内无 Markdown 文件：%s" % root)
        return 2
    urls = extract_urls(md_files)
    if not urls:
        print("✗ 未扫描到任何链接，无可验之物")
        return 2

    print("扫描 %d 个文件，提取链接 %d 条（去重 %d 条）"
          % (len(md_files), len(urls), len(set(urls))))

    if mutate:
        broken, mutated = mutate_first(urls)
        print("\n【定点变异自证】人为改坏链接：%s" % broken)
        print("对变异集合重跑守卫（期望：必红且点名该链接）——")
        failures = run_guards(mutated)
        named = any(broken in f for f in failures)
        for f in failures:
            print("✗ FAIL %s" % f)
        if failures and named:
            print("✓ 自证成立：变异链接被守卫抓到并点名：%s" % broken)
            return 0
        print("✗ 自证失败：变异未被抓到或未点名——校验器不可信")
        return 1

    failures = run_guards(urls)
    for f in failures:
        print("✗ FAIL %s" % f)
    if failures:
        print("\n通过 0 / 失败 %d（逐条点名如上）" % len(failures))
        return 1
    print("\n通过 %d / 失败 0（G1–G5 全过，逐条可达）" % len(set(urls)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
