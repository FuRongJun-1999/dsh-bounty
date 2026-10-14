#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_marker_reverts —— 「静默回退」检查器（把维护手册 §四-2 的人工步骤做成可跑脚本）

    python -X utf8 scripts/check_marker_reverts.py --base origin/main --head HEAD
    python -X utf8 scripts/check_marker_reverts.py --base <sha> --head <sha> --json

## 为什么有这个脚本

`docs/bounty/运行手册_维护者长期任务_v0.1.md` §二 第 8 道（★看删除行）要求：

> `git diff <merge-base>..<PR-head>` 里凡 `^-` 行含**他人**的逐笔留痕注释
> （`★本笔` / `★fix-`）⇒ 该笔在**静默回退**别人已合并的修复。
> 仅看「head 自身绿」会漏判——已实证（见 §四-2）。

而 §七 明文承认这条**没有守卫**：

> 本手册是**流程描述**，不是判据：它本身**没有守卫**。若某轮跳过 §二 的某一道，
> 不会有任何测试变红。**这是本手册当前的已知弱点**——补法是给关键步骤
> （如「删除行检查」）**做成可跑脚本并纳入 CI**，而不是靠这份文本。

本脚本就是那个「可跑脚本」。

## 判据

取 `--base` 与 `--head` 的 **merge-base**，得到 `base..head` 的 diff；
逐条看**删除行**（`^-`，排除 `---` 文件头）：

* 含 `★本笔` 或 `★fix-` 的删除行 ⇒ **报告**；
* 可选 `--exclude <登录名>`：若删除行**同时**出现在 `--author` 自己的新增里
  （即「改写自己的注释」），可选择放行 —— 默认**不放行**（保守：宁多报不漏报）。

**退出码**：`0` = 未发现疑似静默回退；`1` = 发现（逐条列出行号与内容）；`2` = 输入/环境错误。

> **诚实边界**：本脚本只能发现「删除行**含留痕标记**」这一种形态。
> 若某人回退别人的修复时**顺手删掉了标记注释**，本脚本**看不见** ——
> 判据是标记，不是语义。这是它相对人工复核的已知上限。
"""
import argparse
import json
import os
import re
import subprocess
import sys

#: 逐笔留痕标记（维护手册 §二-8 的原文形态）
MARKERS = ("★本笔", "★fix-")
#: 删除行里出现这些前缀的是 git 的文件头，不是内容
_NOT_CONTENT = ("---",)


class RevertError(Exception):
    """输入/环境错误（fail-closed ⇒ 退 2）。"""


def git(args, cwd=None):
    """跑 git 并返回 stdout；调用失败抛 RevertError（不抛裸栈）。"""
    try:
        proc = subprocess.run(["git", *args], capture_output=True, text=True,
                              encoding="utf-8", cwd=cwd)
    except OSError as exc:
        raise RevertError("调不起 git（未安装或不在 PATH？）：%s — %s: %s"
                          % (" ".join(args), type(exc).__name__, exc)) from None
    if proc.returncode:
        raise RevertError("git %s 失败：%s" % (" ".join(args), proc.stderr.strip()[:300]))
    return proc.stdout


def merge_base(base, head, cwd=None) -> str:
    """base 与 head 的 merge-base（无共同祖先 ⇒ 退化为 base）。"""
    try:
        return git(["merge-base", base, head], cwd=cwd).strip()
    except RevertError:
        return base


def diff_deleted_lines(base, head, cwd=None):
    """返回合并后的 diff 文本 = base..head。"""
    mb = merge_base(base, head, cwd=cwd)
    return git(["diff", "--unified=0", mb, head], cwd=cwd), mb


def scan(diff_text):
    """从 diff 文本里抽出「含留痕标记的删除行」。返回 [(行号提示, 原文)]。"""
    out = []
    path = "?"
    no = 0
    for ln in diff_text.splitlines():
        if ln.startswith("+++ "):
            path = ln[4:].strip()
            continue
        if ln.startswith("@@"):
            m = re.search(r"-(\d+)", ln)
            no = int(m.group(1)) if m else 0
            continue
        if ln.startswith("-") and not ln.startswith(_NOT_CONTENT):
            body = ln[1:]
            if any(mk in body for mk in MARKERS):
                out.append((path, no, body))
            no += 1
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="「静默回退」检查器：找出 diff 里**含他人留痕标记的删除行**"
                    "（维护手册 §二-8 的可跑化，§七 点名要求）。")
    ap.add_argument("--base", default="origin/main", help="基线 ref（默认 origin/main）")
    ap.add_argument("--head", default="HEAD", help="待检 ref（默认 HEAD）")
    ap.add_argument("--repo", default="", help="仓目录（默认当前工作目录）")
    ap.add_argument("--json", dest="as_json", action="store_true", help="机读输出")
    ap.add_argument("--markers", default="", help="逗号分隔，覆盖默认标记表")
    args = ap.parse_args(argv)

    global MARKERS
    if args.markers:
        MARKERS = tuple(x.strip() for x in args.markers.split(",") if x.strip())

    cwd = args.repo or None
    try:
        diff_text, mb = diff_deleted_lines(args.base, args.head, cwd=cwd)
    except RevertError as exc:
        sys.stderr.write("[error] %s\n" % exc)
        return 2

    hits = scan(diff_text)
    if args.as_json:
        sys.stdout.write(json.dumps(
            {"base": args.base, "head": args.head, "merge_base": mb,
             "markers": list(MARKERS),
             "hits": [{"path": p, "line": n, "text": b} for p, n, b in hits]},
            ensure_ascii=False, indent=1) + "\n")
    else:
        if not hits:
            print("未发现疑似静默回退：%s..%s（merge-base %s）"
                  % (args.base, args.head, mb[:12]))
            return 0
        for p, n, b in hits:
            sys.stderr.write("[回退] %s:%s  %s\n" % (p, n or "?", b.strip()[:160]))
        sys.stderr.write("[check_marker_reverts] 检出 %d 行含留痕标记的删除 ⇒ 退出 1\n"
                         % len(hits))
    return 0 if not hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
