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

URL_RE = re.compile(r"https?://[^\s\)\]\>\"'`，。；：、]+", re.IGNORECASE)
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
        if not url.lower().startswith("https://"):
            failures.append("[G2 协议守卫] 非 https 链接：%s" % url)
        # G3 占位守卫
        low = url.lower()
        if any(marker in low for marker in PLACEHOLDER_MARKERS):
            failures.append("[G3 占位守卫] 占位链接：%s" % url)
        # G5 深链守卫
        parsed = urllib.parse.urlsplit(url)
        path_str = parsed.path
        if not path_str or path_str == "/":
            failures.append("[G5 深链守卫] 站点根或无具体路径的链接（非深链）：%s" % url)
        elif len(path_str) <= 1:
            failures.append("[G5 深链守卫] 路径过短的链接：%s" % url)

    # G4 可达守卫
    if check_reachability:
        for url in sorted(unique):
            ok, reason = probe(url)
            if not ok:
                failures.append("[G4 可达守卫] 链接不可达 (%s)：%s" % (reason, url))

    return failures


def main():
    if len(sys.argv) < 2:
        print("用法: python -X utf8 scripts/check_links.py <目标目录> [--mutate]", file=sys.stderr)
        sys.exit(2)

    target_dir = Path(sys.argv[1])
    mutate_mode = "--mutate" in sys.argv

    if not target_dir.exists() or not target_dir.is_dir():
        print(f"错误：目录不存在或不是文件夹: {target_dir}", file=sys.stderr)
        sys.exit(2)

    md_files = list(target_dir.glob("**/*.md"))
    if not md_files:
        print(f"错误：在目录 {target_dir} 下未找到任何 Markdown 文件", file=sys.stderr)
        sys.exit(2)

    urls = extract_urls(md_files)
    if not urls:
        print(f"错误：在 {target_dir} 的 Markdown 文件中未提取到任何 HTTP(S) 链接", file=sys.stderr)
        sys.exit(2)

    print(f"[*] 扫描到 {len(md_files)} 个 Markdown 文件，提取到 {len(urls)} 条原始链接（去重后 {len(set(urls))} 条）。")

    if mutate_mode:
        print("[*] 正在执行定点变异自证（--mutate）...")
        sorted_urls = sorted(set(urls))
        original_first = sorted_urls[0]
        
        # 构造变异链接：追加 /__mutated_404__
        if original_first.endswith("/"):
            mutated_first = original_first + "__mutated_404__"
        else:
            mutated_first = original_first + "/__mutated_404__"

        mutated_urls = [mutated_first] + sorted_urls[1:]
        
        print(f"[*] 原第一条链接: {original_first}")
        print(f"[*] 变异后链接: {mutated_first}")

        # 运行变异后的守卫校验
        failures = run_guards(mutated_urls, check_reachability=True)
        
        if failures:
            print("[✓] 自证成功：变异后成功触发了守卫拦截！捕获到以下失败项：")
            for f in failures:
                print(f"    - {f}")
            sys.exit(0)
        else:
            print("[✗] 自证失败：变异后的链接未能触发任何守卫拦截！", file=sys.stderr)
            sys.exit(1)

    else:
        print("[*] 正在运行全部守卫校验（含可达性探测）...")
        failures = run_guards(urls, check_reachability=True)
        
        if failures:
            print(f"[✗] 校验失败，共发现 {len(failures)} 处违规：", file=sys.stderr)
            for f in failures:
                print(f"    - {f}", file=sys.stderr)
            sys.exit(1)
        else:
            print("[✓] 全部守卫与链接连通性校验通过！")
            sys.exit(0)


if __name__ == "__main__":
    main()