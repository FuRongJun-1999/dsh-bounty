#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_fix_has_guard —— 「修复有没有守卫」检查器（把维护手册 §八-2 的人工判据做成可跑脚本）

    python -X utf8 scripts/check_fix_has_guard.py --base origin/main --head HEAD
    python -X utf8 scripts/check_fix_has_guard.py --base <sha> --head <sha> --json

## 为什么有这个脚本

`docs/bounty/运行手册_维护者长期任务_v0.1.md` §八「编制后新增实证」2026-10-14 第 2 条：

> **修复类 PR 可能「零守卫」**：只改 `scripts/` 不改 `tests/` 的修复，合并后**没有任何守卫
> 拦得住它的回归**。判据：`git diff --name-only` 里没有 `tests/` 路径。处置：修复正确 ＋
> 回归绿 ⇒ 照合，但**回执里必须写明缺口**并建议补定点变异。另需查**同类既有实现是否也零守卫**
> （如 `_seq` 在测试文件里出现 0 次）——若也是，属**既有缺口**而非本笔引入，不该只挡本笔。

而 §七 承认手册本身没有守卫：

> 本手册是**流程描述**，不是判据……**这是本手册当前的已知弱点**——补法是给关键步骤
> （如「删除行检查」）**做成可跑脚本并纳入 CI**，而不是靠这份文本。

本脚本把 §八-2 那条**判据**机械化（人力仍负责「处置」：照合 / 打回 / 记缺口）。

## 判据（逐字对齐 §八-2）

对 `--base`..`--head` 的 diff：

1. 取变更文件清单（`git diff --name-only`）；
2. **改了 `scripts/` 却没改 `tests/`** ⇒ 报「疑似零守卫的修复」；
3. 可选 `--similar <符号名>`：查该符号名在 `tests/` 下的出现次数（0 次 ⇒ 报「同类既有实现也零守卫」，
   属**既有缺口**，与第 2 步的「本笔引入」分开列）。

**退出码**：`0` = 未见「改 scripts/ 未改 tests/」；`1` = 见到；`2` = 输入/环境错误。

> **诚实边界**：本脚本判的是**文件的覆盖面**，不是**判据的有效性**。
> 一个 PR 改了 `tests/` 也可能只是在改无关断言；只改 `scripts/` 也可能是**纯文本/注释**改动。
> 它把 §八-2 的**第一层筛选**机械化，**第二层（判据是否真锚在本次修复上）仍需人工**。
"""
import argparse
import json
import os
import subprocess
import sys


class GuardCheckError(Exception):
    """输入/环境错误（fail-closed ⇒ 退 2）。"""


#: 实现面 / 守卫面的目录前缀（本仓体例）
IMPL_DIRS = ("scripts/",)
TEST_DIRS = ("tests/",)


def git(args, cwd=None):
    try:
        proc = subprocess.run(["git", *args], capture_output=True, text=True,
                              encoding="utf-8", cwd=cwd)
    except OSError as exc:
        raise GuardCheckError("调不起 git（未安装或不在 PATH？）：%s — %s: %s"
                              % (" ".join(args), type(exc).__name__, exc)) from None
    if proc.returncode:
        raise GuardCheckError("git %s 失败：%s" % (" ".join(args), proc.stderr.strip()[:300]))
    return proc.stdout


def merge_base(base, head, cwd=None) -> str:
    try:
        return git(["merge-base", base, head], cwd=cwd).strip()
    except GuardCheckError:
        return base


def changed_files(base, head, cwd=None):
    mb = merge_base(base, head, cwd=cwd)
    out = git(["diff", "--name-only", mb, head], cwd=cwd)
    return [x.strip() for x in out.splitlines() if x.strip()], mb


def classify(files):
    """返回 (改了实现面的文件, 改了守卫面的文件)。"""
    impl = [f for f in files if any(f.startswith(d) for d in IMPL_DIRS)]
    test = [f for f in files if any(f.startswith(d) for d in TEST_DIRS)]
    return impl, test


def count_in_tests(symbol: str, cwd=None) -> int:
    """符号名在 tests/ 下的出现次数（0 次 ⇒ 同类既有实现也零守卫）。"""
    try:
        out = git(["grep", "-c", "-F", symbol, "--", "tests/"], cwd=cwd)
    except GuardCheckError:
        return 0
    n = 0
    for ln in out.splitlines():
        try:
            n += int(ln.rsplit(":", 1)[-1])
        except (ValueError, IndexError):
            continue
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="「修复有没有守卫」检查器（维护手册 §八-2 的可跑化；§七 点名要求把关键步骤做成脚本）。")
    ap.add_argument("--base", default="origin/main", help="基线 ref（默认 origin/main）")
    ap.add_argument("--head", default="HEAD", help="待检 ref（默认 HEAD）")
    ap.add_argument("--repo", default="", help="仓目录（默认当前工作目录）")
    ap.add_argument("--json", dest="as_json", action="store_true", help="机读输出")
    ap.add_argument("--similar", default="",
                    help="可选：符号名。若它在 tests/ 下 0 次出现 ⇒ 报「同类既有实现也零守卫」"
                         "（§八-2 要求把「既有缺口」与本笔引入分开记）")
    args = ap.parse_args(argv)

    cwd = args.repo or None
    try:
        files, mb = changed_files(args.base, args.head, cwd=cwd)
    except GuardCheckError as exc:
        sys.stderr.write("[error] %s\n" % exc)
        return 2

    impl, test = classify(files)
    gap = bool(impl) and not test
    similar_zero = None
    if args.similar:
        similar_zero = (count_in_tests(args.similar, cwd=cwd) == 0)

    if args.as_json:
        sys.stdout.write(json.dumps(
            {"base": args.base, "head": args.head, "merge_base": mb,
             "changed": files, "impl": impl, "tests": test,
             "missing_guard": gap,
             "similar": args.similar or None,
             "similar_absent_in_tests": similar_zero},
            ensure_ascii=False, indent=1) + "\n")
    else:
        if not impl:
            print("未见实现面改动：%s..%s（merge-base %s）" % (args.base, args.head, mb[:12]))
            return 0
        if test:
            print("实现面 + 守卫面都改了（%d 个实现文件 / %d 个测试文件）：%s..%s"
                  % (len(impl), len(test), args.base, args.head))
            return 0
        sys.stderr.write("[缺口] 改了 %d 个实现文件但**未改任何 tests/** ⇒ 疑似零守卫的修复：\n"
                         % len(impl))
        for f in impl:
            sys.stderr.write("         %s\n" % f)
        if similar_zero is True:
            sys.stderr.write("[既有] 另：%r 在 tests/ 下 **0 次**出现 ⇒ 同类既有实现也零守卫，"
                             "属**既有缺口**而非本笔引入（§八-2 要求分开记）\n" % args.similar)
        sys.stderr.write("[check_fix_has_guard] 检出疑似零守卫的修复 ⇒ 退出 1"
                         "（处置：修复正确 ＋ 回归绿 ⇒ 照合，但**回执里须写明缺口**）\n")
    return 1 if gap else 0


if __name__ == "__main__":
    raise SystemExit(main())
