#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵枢悬赏板 · 每日贡献表生成器（从账本机械生成；产物勿手改）

生效条件：账本 JSON 存在且为 {"events": [...]} 时，按 `day`（缺省取 ts 前 10 位）
分组 **settle** 事件，渲染 markdown 贡献表并写盘；同一账本 ⇒ 逐字节同一文本。

用法：
    python -X utf8 scripts/daily_table.py --ledger docs/bounty/ledger.json \
        --out docs/bounty/贡献表.md

边界（规格 V2/V4）：本站只出**声誉分**与两条独立的轴（难度 / 影响等级）；
金额、汇率、合成权重不进站。`--check` 对渲染结果做确定性自检（跑两遍比对）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # <仓根>/scripts
REPO = os.path.dirname(HERE)                               # <仓根>
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bounty_board as bb                                            # noqa: E402

#: 难度 → base 分（**不另立一份表**——直接取权威单点 `bounty_board.DIFFICULTY_SCORES`；
#: import 体例与 `build_site.py` 同款，`build_site.py:68` 亦写明「改口径只改
#: `scripts/bounty_board.py` 的 `DIFFICULTY_SCORES`」）。
#:
#: ★本笔修正：旧实现在下方 `base is None` 分支里内联了一份
#: `{"easy": 1, "medium": 3, "hard": 6, "expert": 10}` —— 这是**第三份拷贝**
#: （另两份在 `bounty_board.py:104` 与 `bounty_list.py:19`），且**没有任何守卫**
#: 比对它与权威表（`test_bounty_list.py` 的 A15 只覆盖前两份）。后果：改权威表后
#: `贡献表.md` 的 `base` 列会**静默陈旧**。而账本事件**不带 `difficulty_base`**
#: ⇒ 该分支恒真、这份拷贝**永远在热路径上**（它是维护者每日计分要看的表）。
_DIFF_BASE = {k.split(":", 1)[-1]: v for k, v in bb.DIFFICULTY_SCORES.items()}

#: 计分口径（与《贡献结算表 v0.1》§三 同源；改口径只改本注记与账本事件）。
#: ★本笔修正：旧注记"标准交付取中性点 round = 1 ⇒ Δ = base"命名易混、
#: 原注记未写出 round→r 的映射（`bounty_board.quality_delta`：`r = max(0, rounds - 1)`，
#: 首交付 rounds=1 ⇒ r=0 ⇒ Δ=2×base）。现明确写出映射关系。
SCORE_NOTE = ("Δ = max(1, round_half_up(base × 2 / (r + 1)))，"
              "r = max(0, rounds - 1)。首交付 rounds=1 ⇒ r=0 ⇒ Δ=2×base；"
              "返工一次 rounds=2 ⇒ r=1（中性点）⇒ Δ=base。")

#: 金额边界注记——与 bounty_board.NOTE_NO_MONEY 同一条硬边界。
NOTE_NO_MONEY = ("本站只做声誉分与价值评价；金额不进站。两轴（难度 / 影响等级）"
                 "分别记录，合成权重与资金换算属使用者侧。")


class DailyTableError(Exception):
    """贡献表生成错误（账本不可读 / 结构不符）。"""


# 生效条件：path 为账本 JSON 路径时返回 events 列表（不存在 → []；坏 JSON 或结构不符抛错）。
def load_ledger(path):
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError as exc:
        raise DailyTableError(f"账本不是合法 JSON：{path}（{exc}）")
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and isinstance(doc.get("events"), list):
        return doc["events"]
    raise DailyTableError(f"账本结构不符（须为 {{'events': [...]}}）：{path}")


# 生效条件：传入任意 issue 号可迭代时返回压缩显示串——连续段压成 #a–#b，非连续逐列；
# 空集返回「—」。纯函数、确定性（同一集合 ⇒ 同一文本）。
def fmt_issues(nums):
    vals = sorted({int(n) for n in (nums or []) if str(n).strip().isdigit()})
    if not vals:
        return "—"
    out, i = [], 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[j + 1] == vals[j] + 1:
            j += 1
        out.append(f"#{vals[i]}" if i == j else f"#{vals[i]}–#{vals[j]}")
        i = j + 1
    return " ".join(out)


# 生效条件：传入事件时返回其覆盖的 issue 号列表——优先读显式 covers（工作项合并后
# 一条事件覆盖多条 issue），缺省回退到单条 issue 字段；不猜测、不发明。
def covers_of(ev):
    c = ev.get("covers")
    if isinstance(c, list) and c:
        return [int(x) for x in c if str(x).strip().isdigit()]
    try:
        n = int(ev.get("issue") or 0)
    except (TypeError, ValueError):
        return []
    return [n] if n else []


# 生效条件：events 为账本事件列表时返回 {结算日: [settle 事件]}——日期取 day 字段，
# 缺省回退 ts 前 10 位，再缺省归「未标日」；只收 settle（贡献表是结算视图）。
def group_by_day(events):
    days = {}
    for ev in events or []:
        # ★本笔：**元素形状判据**。贡献表由账本机械生成，账本事件里混进非对象
        # ⇒ `AttributeError`，而本件 docstring 承诺确定性渲染。
        if not isinstance(ev, dict):
            continue
        if ev.get("action") != "settle":
            continue
        d = (ev.get("day") or (ev.get("ts") or "")[:10] or "未标日")
        days.setdefault(d, []).append(ev)
    return days


# 生效条件：events 为账本事件列表时返回贡献表 markdown 全文（确定性：同一账本 ⇒
# 逐字节同一文本）；不写生成时刻（防生成件无谓翻滚）。
def render(events):
    events = list(events or [])
    days = group_by_day(events)
    n_settle = sum(len(v) for v in days.values())
    lines = [
        "# 灵枢悬赏板 · 每日贡献表",
        "",
        "> 本页由 `scripts/daily_table.py` 从 `docs/bounty/ledger.json`"
        "（append-only 事件流）**机械生成**——勿手改，手改会在下一次生成时被覆盖。",
        f"> 账本事件数：{len(events)} ｜ 结算项：{n_settle} ｜ 结算日：{len(days)}",
        "",
        f"计分口径：{SCORE_NOTE}",
        "",
        f"> {NOTE_NO_MONEY}",
        "",
    ]
    if not days:
        lines += ["## 结算记录", "",
                  "（暂无结算——账本为空或尚无 `settle` 事件；"
                  "第一条结算落账后本表自动出现。）", ""]
    else:
        total = 0
        for d in sorted(days, reverse=True):
            evs = sorted(days[d], key=lambda e: (e.get("holder") or "",
                                                 e.get("project") or ""))
            sub = sum(int(e.get("delta") or 0) for e in evs)
            total += sub
            lines += [f"## {d}（结算 {len(evs)} 项 · 合计 {sub} 分）", "",
                      "| # | 贡献者 | 项目 | 难度 | base | Δ | 影响 | 覆盖 issue | 依据 |",
                      "|---|---|---|---|---|---|---|---|---|"]
            for i, ev in enumerate(evs, 1):
                base = ev.get("difficulty_base")
                if base is None:
                    # ★本笔：取权威单点 `_DIFF_BASE`（由 `bb.DIFFICULTY_SCORES` 派生），
                    # 不再内联第三份拷贝。默认值 `1` 与旧实现的 `.get(…, 1)` 逐位一致。
                    base = _DIFF_BASE.get(ev.get("difficulty") or "", 1)
                f = ev.get("formula") or {}
                rnd = f.get("round")
                diff = (ev.get("difficulty") or "") + (f"（round={rnd}）" if rnd is not None else "")
                lines.append(
                    f"| {i} | @{ev.get('holder') or ev.get('actor') or '—'} "
                    f"| {ev.get('project') or '—'} | {diff or '—'} | {base} "
                    f"| **{int(ev.get('delta') or 0)}** | {ev.get('impact') or '—'} "
                    f"| {fmt_issues(covers_of(ev))} "
                    f"| {(ev.get('reason') or '').replace('|', '/')} |")
            lines.append("")
            per = {}
            for ev in evs:
                who = ev.get("holder") or ev.get("actor") or "—"
                row = per.setdefault(who, {"d": 0, "n": 0, "is": []})
                row["d"] += int(ev.get("delta") or 0)
                row["n"] += 1
                row["is"] += covers_of(ev)
            lines += ["### 按人合计", "",
                      "| 贡献者 | 声誉分 | 项数 | 覆盖 issue |", "|---|---|---|---|"]
            for who, row in sorted(per.items(), key=lambda x: (-x[1]["d"], x[0])):
                lines.append(f"| @{who} | **{row['d']}** | {row['n']} | "
                             f"{fmt_issues(row['is'])} |")
            lines.append("")
        # 累计（全部结算日）
        cum = {}
        for d, evs in days.items():
            for ev in evs:
                who = ev.get("holder") or ev.get("actor") or "—"
                row = cum.setdefault(who, {"d": 0, "n": 0, "is": []})
                row["d"] += int(ev.get("delta") or 0)
                row["n"] += 1
                row["is"] += covers_of(ev)
        lines += ["## 累计（全部结算日）", "",
                  f"合计 **{total}** 分 · {n_settle} 项 · {len(cum)} 位贡献者", "",
                  "| 贡献者 | 声誉分 | 项数 | 覆盖 issue |", "|---|---|---|---|"]
        for who, row in sorted(cum.items(), key=lambda x: (-x[1]["d"], x[0])):
            lines.append(f"| @{who} | **{row['d']}** | {row['n']} | "
                         f"{fmt_issues(row['is'])} |")
        lines.append("")
    lines += ["---", "",
              "本页由 `scripts/daily_table.py --ledger docs/bounty/ledger.json "
              "--out docs/bounty/贡献表.md` 生成；"
              "荣誉榜见 [board.md](board.md)，规则见 [README.md](README.md)。", ""]
    return "\n".join(lines)


# 生效条件：argv 为命令行参数（缺省取 sys.argv[1:]）时写贡献表并返回 0；
# --check 只做确定性自检（渲染两遍比对）不写盘。
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="灵枢悬赏板 · 每日贡献表生成器")
    ap.add_argument("--ledger", default="docs/bounty/ledger.json", help="账本 JSON 路径")
    ap.add_argument("--out", default="", help="贡献表 markdown 输出路径")
    ap.add_argument("--check", action="store_true",
                    help="确定性自检（渲染两遍比对，不写盘）")
    args = ap.parse_args(argv)
    try:
        events = load_ledger(args.ledger)
        text = render(events)
        if args.check:
            again = render(events)
            if text != again:
                print("确定性自检失败：两次渲染不一致", file=sys.stderr)
                return 1
            print(f"确定性自检通过（账本 {len(events)} 条事件）")
            return 0
        if not args.out:
            print(text)
            return 0
        parent = os.path.dirname(os.path.abspath(args.out))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print(f"贡献表已生成：{args.out}（账本 {len(events)} 条事件）")
        return 0
    except DailyTableError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
