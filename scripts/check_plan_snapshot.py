# -*- coding: utf-8 -*-
"""check_plan_snapshot —— 把 GitHub 的 issue 面导出成 check_plan 可读的快照（只读）。

为什么单独一件：`scripts/check_plan.py` **零网络**（CI 不发起网络请求，见《悬赏与项目管理
v0.2》§六）。issue 面的真源是 issue 线程本身，本地快照只是它的**只读投影**——而「取投影」
是线上动作，所以拆成这件独立的、**需要 gh 登录**的导出器；对账器本身不必知道网络存在。

**默认不把投影提交进仓**（本件是可选运维工具，不进 `--dry-run` 的必需路径）：提交一份
本地快照会让 `--dry-run` 悄悄依赖它，从而「CI 能跑」变成「有网/有 gh 才跑得动」。
跑法：
  python -X utf8 scripts/check_plan_snapshot.py --out <临时路径>
  python -X utf8 scripts/check_plan.py --dry-run --issues <临时路径>

用法（需已登录 `gh`）：
  python -X utf8 scripts/check_plan_snapshot.py                 # 导出到默认路径
  python -X utf8 scripts/check_plan_snapshot.py --out <path>
  python -X utf8 scripts/check_plan_snapshot.py --repo <org>/<repo>
退出码：0 = 导出成功；1 = gh 调用失败 / 未登录。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(REPO_DIR, "docs", "bounty", "issues-state.json")
DEFAULT_REPO = "FuRongJun-1999/dsh-bounty"
MARKER_RE = re.compile(r"<!--\s*bounty:v1\s+\{.*?\}\s*-->", re.DOTALL)


# 生效条件：args 为 gh 参数列表时返回其 JSON 行数组；失败抛 RuntimeError（不静默）。
def _gh_lines(args):
    """跑 gh api，返回 stdout 的非空行（**不要求是 JSON**——base64 输出用它）。"""
    # ★本笔：捕获 **`OSError`**（`PATH` 里没有 `gh` ⇒ `subprocess.run` 抛
    # `FileNotFoundError: [WinError 2]`）。旧实现只判 `proc.returncode`，
    # 于是「gh 没装」这条**最常见的坏法**穿透成裸 `FileNotFoundError` 栈：
    #   · 违背本函数自己的 docstring 承诺「失败抛 **RuntimeError**（不静默）」；
    #   · 违背本文件 docstring 承诺「退出码：0 = 导出成功；**1 = gh 调用失败 / 未登录**」
    #     —— `main()` 只接 `RuntimeError`，这个异常直接穿出去；
    #   · 退码**巧合**仍是 1（Python 未捕获异常退 1），受损的是**错误分类**与
    #     `main()` 的返回值契约（而不是退码）。
    try:
        proc = subprocess.run(["gh", "api", "--paginate", *args],
                              capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"调不起 gh（未安装或不在 PATH？）：{' '.join(args)} — "
            f"{type(exc).__name__}: {exc}") from None
    if proc.returncode:
        raise RuntimeError(f"gh 调用失败：{' '.join(args)} — {proc.stderr.strip()[:300]}")
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def _gh_json_lines(args):
    """跑 gh api，按行解析 JSON（--jq 需产出逐行 JSON）。"""
    out = []
    for line in _gh_lines(args):
        try:
            out.append(json.loads(line))
        except ValueError as exc:
            raise RuntimeError(
                f"gh 输出不是逐行 JSON：{' '.join(args)} — 首 200 字符：{line[:200]!r}（{exc}）"
            ) from None
    return out


# 生效条件：repo 为 "org/name" 时返回快照文档 {_schema, source, items}；items 为
# [{number, labels, comments}]，comments **只留 bounty:v1 机器标记**（对账只需要它）。
def build_snapshot(repo=DEFAULT_REPO):
    issues = _gh_json_lines([
        f"repos/{repo}/issues?state=all&per_page=100",
        "--jq", ".[] | {number, labels: [.labels[].name], author: (.user.login // \"\"), "
                "n: (.comments|tostring)}",
    ])
    items = []
    for it in issues:
        num = int(it["number"])
        markers = []
        if int(it.get("n") or 0):
            # 评论正文可能多行 ⇒ 走 base64 一行一条（否则按行解析 JSON 会被正文换行打断）。
            bodies = _gh_lines([f"repos/{repo}/issues/{num}/comments?per_page=100",
                                "--jq", ".[] | .body | @base64"])
            for b64 in bodies:
                body = base64.b64decode(b64).decode("utf-8", "replace")
                markers.extend(MARKER_RE.findall(body))
        items.append({"number": num, "labels": list(it.get("labels") or []),
                      "author": str(it.get("author") or ""), "comments": markers})
    return {
        "_schema": "check_plan issue 快照（只读导出；comments 只留 bounty:v1 机器标记）",
        "source": f"gh api repos/{repo}/issues?state=all + 逐号 comments —— 由 "
                  f"scripts/check_plan_snapshot.py 生成（手改会被下次导出覆盖）",
        "repo": repo,
        "items": items,
    }


def write_snapshot(doc, path=DEFAULT_OUT):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check_plan_snapshot.py",
                                 description="导出 dsh-bounty issue 面快照（只读）")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="org/name（缺省本站）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出路径")
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        doc = build_snapshot(args.repo)
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    path = write_snapshot(doc, args.out)
    n_mark = sum(len(i["comments"]) for i in doc["items"])
    print(f"[ok] {path} ｜ issue {len(doc['items'])} 条 ｜ 机器标记 {n_mark} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
