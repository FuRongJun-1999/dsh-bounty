# -*- coding: utf-8 -*-
"""test_daily_table —— 每日贡献表生成器守卫（断言 ＋ 定点变异自证）。

对象：`scripts/daily_table.py`（**纯渲染层**——零网络、只读账本、纯函数）。
上游：`docs/bounty/ledger.json`（append-only 事件流）；产物：`docs/bounty/贡献表.md`。

为什么另立本件：贡献表的每个数字都进**公开声誉榜**——判据不设反面证明就等于没有判据
（本仓惯例：注入必红——把判据短路，断言必转红并点名）。故本件 =
①逐条正反断言 ＋ ②每条判据一个**定点变异**（短路该判据 ⇒ 对应断言**必然转红**且
**恰好**转红，多红=断言语义纠缠、少红=判据空转）。

断言组：
  [D1] 空账本 → 「暂无结算」形态
  [D2] 按 `day` 分节且日期倒序
  [D3] 工作项覆盖：`covers` 优先于单条 `issue`
  [D4] issue 号压缩显示（连续段 → #a–#b）
  [D5] 按人合计累加
  [D6] 累计跨结算日
  [D7] 确定性（同一账本 ⇒ 逐字节同一文本）
  [D8] 只收 `settle` 事件（deliver/claim 等不入表）
  [D9] 金额边界注记在（规格 V2/V4）
  [D12] 主表列集固定（只列分类与编号）

用法：
  python -X utf8 tests/test_daily_table.py            # 正向：全断言
  python -X utf8 tests/test_daily_table.py --mutate   # 定点变异自证（逐条必红）
  python -X utf8 tests/test_daily_table.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中期望红项；1 = 有断言失败 / 变异未按预期转红；
        2 = ANCHOR-MISS（变异锚点在实现里命中次数 ≠1——实现漂移即硬失败）。
"""
from __future__ import annotations

import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import daily_table as dt                                            # noqa: E402

IMPL = os.path.join(SCRIPTS, "daily_table.py")

_red = []


def ok(name, cond, detail=""):
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))
        _red.append(name.split(" ")[0])


def _ev(i, holder, delta, day="2026-10-12", action="settle", **kw):
    e = {"ts": day + "T12:00:00Z", "issue": i, "action": action, "actor": "m",
         "holder": holder, "delta": delta, "day": day}
    e.update(kw)
    return e


def run_checks():
    global _red
    _red = []
    # D1 空账本
    ok("D1 空账本 → 暂无结算", "暂无结算" in dt.render([]))

    # D2 按 day 分节 + 倒序
    t = dt.render([_ev(1, "a", 3, day="2026-10-11"), _ev(2, "b", 6, day="2026-10-12")])
    ok("D2 两个结算日分节", "## 2026-10-11" in t and "## 2026-10-12" in t)
    ok("D2b 日期倒序（新在前）", t.index("## 2026-10-12") < t.index("## 2026-10-11"))

    # D3 covers 优先
    t = dt.render([_ev(9, "a", 6, covers=[1, 2, 3])])
    ok("D3 covers 展开为覆盖 issue", "#1–#3" in t, t[:0])
    ok("D3b covers 优先于单条 issue", "#9" not in t)

    # D4 压缩显示
    ok("D4 连续段压缩", dt.fmt_issues([1, 2, 3, 7, 9, 10]) == "#1–#3 #7 #9–#10",
       dt.fmt_issues([1, 2, 3, 7, 9, 10]))
    ok("D4b 空集 → 破折号", dt.fmt_issues([]) == "—")
    ok("D4c 去重且升序", dt.fmt_issues([3, 3, 1]) == "#1 #3")

    # D5 按人合计
    t = dt.render([_ev(1, "a", 6), _ev(2, "a", 10), _ev(3, "b", 3)])
    _seg = t.split("### 按人合计")[1].split("## 累计")[0]
    ok("D5 按人合计累加（只看当日小节，避开累计表救场）", "| @a | **16** | 2 |" in _seg)
    ok("D5b 日合计行", "合计 19 分" in t)

    # D6 累计跨日
    t = dt.render([_ev(1, "a", 6, day="2026-10-11"), _ev(2, "a", 10, day="2026-10-12")])
    ok("D6 累计跨结算日", "| @a | **16** | 2 |" in t and t.count("## 2026-") == 2)

    # D7 确定性
    evs = [_ev(1, "a", 6), _ev(2, "b", 3)]
    ok("D7 确定性（两遍同文本）", dt.render(evs) == dt.render(evs))

    # D8 只收 settle
    t = dt.render([_ev(1, "a", 6, action="deliver"), _ev(2, "b", 3)])
    ok("D8 非 settle 不入表", "结算 1 项" in t and "@b" in t and "@a" not in t)

    # D9 金额边界
    ok("D9 金额边界注记在", "金额不进站" in dt.render([_ev(1, "a", 3)]))

    # D12 主表列集固定（精简后可读性）：只列分类与编号，不得回涨「依据」列
    _t = dt.render([_ev(1, "a", 3, reason="a|b", difficulty="hard", project="memory")])
    ok("D12 主表列集固定为 7 列",
       "| # | 贡献者 | 项目 | 难度 | Δ | 影响 | 覆盖 issue |" in _t, _t[:0])
    ok("D12b 主表不含「依据」列（reason 不进表）",
       "| 依据 |" not in _t and "a/b" not in _t, _t[:0])
    ok("D12c 主表不含「base」列（与难度/Δ 冗余）", "| base |" not in _t, _t[:0])
    ok("D12d 按人合计/累计不复述编号列",
       "| 贡献者 | 声誉分 | 项数 |" in _t and "| 贡献者 | 声誉分 | 项数 | 覆盖 issue |" not in _t)


_MUTATIONS = (
    ("M1 关 covers 优先（工作项覆盖丢失）",
     "    c = ev.get(\"covers\")",
     "    c = None  # MUT",
     {"D3", "D3b"}),
    ("M2 关连续段压缩（issue 列不压缩）",
     "        while j + 1 < len(vals) and vals[j + 1] == vals[j] + 1:",
     "        while False:  # MUT",
     {"D3", "D4"}),
    ("M3 不过滤 action（deliver 也入表）",
     "        if ev.get(\"action\") != \"settle\":",
     "        if False:  # MUT",
     {"D8"}),
    ("M4 按人合计不累加（只记最后一条）",
     "                row = per.setdefault(who, {\"d\": 0, \"n\": 0})" + chr(10) +
     "                row[\"d\"] += int(ev.get(\"delta\") or 0)",
     "                row = per.setdefault(who, {\"d\": 0, \"n\": 0})" + chr(10) +
     "                row[\"d\"] = int(ev.get(\"delta\") or 0)  # MUT",
     {"D5"}),
    # ★本笔：表体量闸——把「依据」列塞回主表 ⇒ D12b 必红（防表重新臃肿回 235 KB）。
    ("M5 主表回涨「依据」列（体量回退）",
     "\"| # | 贡献者 | 项目 | 难度 | Δ | 影响 | 覆盖 issue |\",",
     "\"| # | 贡献者 | 项目 | 难度 | Δ | 影响 | 覆盖 issue | 依据 |\",  # MUT",
     {"D12b"}),
)

#: 变异 → (被测函数名, 跑哪些断言组)
_MUT_TARGETS = (
    ("M1", "covers_of", run_checks),
    ("M2", "fmt_issues", run_checks),
    ("M3", "group_by_day", run_checks),
    ("M4", "render", run_checks),
    ("M5", "render", run_checks),
)


class AnchorMiss(Exception):
    pass


# 生效条件：fn_name 为模块内函数名、old 为唯一锚点、new 为替换文本时，用
# inspect.getsource 取该函数源码，就地 exec 到模块全局（运行中的实现被替换），
# 返回复原函数；锚点命中次数 ≠1 抛 AnchorMiss（调用方记 ANCHOR-MISS）。
def _mut_source(fn_name, old, new):
    orig = getattr(dt, fn_name)
    src = inspect.getsource(orig)
    if src.count(old) != 1:
        raise AnchorMiss(f"{fn_name}: 锚点命中 {src.count(old)} 次（期望 1）：{old!r}")
    exec(compile(src.replace(old, new), f"<daily-{fn_name}-mut>", "exec"), vars(dt))

    def _restore():
        setattr(dt, fn_name, orig)
    return _restore


def _mutate_mode():
    base_red = set()
    run_checks()
    base_red = set(_red)
    print(f"\n  未变异基线：红项 {len(base_red)} "
          f"{'（应为 0）' if not base_red else sorted(base_red)}")
    bad = []
    if base_red:
        bad.append(f"基线即转红：{sorted(base_red)}")
    for (name, old, new, expect), (_mid, fn_name, fn) in zip(_MUTATIONS, _MUT_TARGETS):
        try:
            restore = _mut_source(fn_name, old, new)
        except AnchorMiss as exc:
            print(f"  [ANCHOR-MISS] {name} — {exc}")
            return 2
        try:
            fn()
            got = set(_red)
        finally:
            restore()
        if got == set(expect):
            print(f"  [PASS] {name} → 恰好转红 {sorted(got)}")
        else:
            print(f"  [FAIL] {name} → 期望 {sorted(expect)}，实得 {sorted(got)}")
            bad.append(name)
    run_checks()
    if set(_red):
        bad.append(f"复原后仍红：{sorted(set(_red))}")
    n_ok = len(_MUTATIONS) - len([b for b in bad if any(b == m[0] for m in _MUTATIONS)])
    print(f"\n  变异自证：{n_ok}/{len(_MUTATIONS)} 通过"
          + (f" ｜ 问题：{bad}" if bad else ""))
    return 1 if bad else 0


def main(argv=None):
    global _red
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--list" in argv:
        for name, _o, _n, exp in _MUTATIONS:
            print(f"  {name} → 期望转红 {sorted(exp)}")
        return 0
    if "--mutate" in argv:
        return _mutate_mode()
    print("=== test_daily_table 正向断言 ===")
    run_checks()
    print(f"\n  失败 {len(_red)}")
    if _red:
        print(f"  失败项：{sorted(set(_red))}")
        return 1
    print("  ALL OK（反面证明见 --mutate）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
