# -*- coding: utf-8 -*-
"""test_check_plan —— 三方对账校验件守卫（断言 ＋ 定点变异自证）。

对象：`scripts/check_plan.py`（**纯 stdlib、零网络**的只读对账件）。
上游：`docs/bounty/ledger.json`（账本面）＋ issue 快照（标签面/标记面）。
对齐：《悬赏与项目管理 v0.2》§二–§四。

为什么另立本件：对账件的产物会被用来**判定别人是否漏账**——判据不设反面证明就等于没有
判据。故本件 = ①逐条正反断言 ＋ ②每条判据一个**定点变异**（短路该判据 ⇒ 对应断言
**必然转红**且**恰好**转红，多红=断言语义纠缠、少红=判据空转）。

断言组：
  [D1] 一致行：标记>标签>默认open 的优先级、账本态派生正确
  [D2] 态冲突：账本与标签不一致 ⇒ 点名该 issue
  [D3] 缺账本事件：有进程态标签而账本查无此号 ⇒ 点名
  [D4] 缺标签：账本有事件而 issue 面无 bounty 入选标记 ⇒ 点名
  [D5] covers 覆盖号不代入三方表（不把一次结算覆盖十条误报十条）
  [D6] 普通 issue（无 bounty 标签、账本无事件）不代入
  [D7] 多态标签自相矛盾要报（标签面自身矛盾，非两面冲突）
  [D8] 确定性（同一输入两遍同文本）
  [D9] 退出码：有不一致仍为 0（真问题 ≠ 脚本故障）；坏输入为 1
  [D10] 缺快照不得静默当「一致」
  [D11] 零第三方依赖 / 不碰计分口径（回归闸）

用法：
  python -X utf8 tests/test_check_plan.py            # 正向：全断言
  python -X utf8 tests/test_check_plan.py --mutate   # 定点变异自证（逐条必红）
  python -X utf8 tests/test_check_plan.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中期望红项；1 = 有断言失败 / 变异未按预期转红；
        2 = ANCHOR-MISS（变异锚点在实现里命中次数 ≠1——实现漂移即硬失败）。
"""
from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import check_plan as cp                                               # noqa: E402

IMPL = os.path.join(SCRIPTS, "check_plan.py")
PY = sys.executable or "python"
FIXDIR = os.path.join(HERE, "fixtures")
#: 「无漂移」用的临时夹具（由 _fixture 去掉全部缺陷行生成 ⇒ 不会随线上数据变化）。
GOLDEN_OK_ISSUES = os.path.join(FIXDIR, "__ok_issues.json")
GOLDEN_OK_LEDGER = os.path.join(FIXDIR, "__ok_ledger.json")
GOLDEN_DRIFT_ISSUES = os.path.join(FIXDIR, "__drift_issues.json")
GOLDEN_DRIFT_LEDGER = os.path.join(FIXDIR, "__drift_ledger.json")
GOLDEN_STATE = os.path.join(FIXDIR, "__state_probe.json")

#: `--state` 探针（bounty_board 同格式：issues{key:{number,labels,markers[]}} ＋ ledger[]）。
#: 覆盖两条腿：#1 三面一致、#8 声明态 claimed 但账本无（缺账本事件）。
_STATE_PROBE = {"_note": "check_plan --state 探针（临时件，跑完即删）",
                "issues": {
                    "1": {"number": 1, "labels": ["bounty", "difficulty:hard", "bounty:settled"],
                          "author": "m", "markers": [{"seq": 4, "state": "settled"}], "history": []},
                    "2": {"number": 2, "labels": ["bounty", "difficulty:medium", "bounty:settled"],
                          "author": "m", "markers": [{"seq": 2, "state": "settled"}], "history": []},
                    "8": {"number": 8, "labels": ["bounty", "difficulty:hard", "bounty:claimed"],
                          "author": "m", "markers": [], "history": []}},
                "ledger": [{"ts": "2026-10-12T12:00:00Z", "issue": 1, "action": "settle"},
                           {"ts": "2026-10-12T13:00:00Z", "issue": 2, "action": "settle"}]}

_red = []


def ok(name, cond, detail=""):
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))
        _red.append(name.split(" ")[0])


# 生效条件：三组输入给定时返回 (issues, events)——issues 为 [(号, 标签, 评论)]，events 为账本事件。
def _fixture():
    mk = lambda n, st, seq: [f"<!-- bounty:v1 {{\"seq\": {seq}, \"state\": \"{st}\"}} -->"]
    issues = [
        (1, ("bounty", "difficulty:hard", "bounty:settled"), mk(1, "settled", 4)),   # 一致
        (2, ("bounty", "difficulty:medium", "bounty:claimed"), mk(2, "claimed", 2)),  # 账本 settled
        (3, ("bounty", "difficulty:hard", "bounty:delivered"), mk(3, "delivered", 3)),  # 账本无
        (4, (), mk(4, "settled", 5)),                                                 # 无标签、账本有
        (5, ("bounty", "difficulty:easy", "bounty:claimed", "bounty:delivered"),
         mk(5, "claimed", 6)),                                                        # 多态标签
        (6, (), []),                                                                   # 普通 issue
        (7, ("bounty", "difficulty:expert"), []),        # 只有入选标记、无声明态 ⇒ 推导 open，不需账本背书
        (8, ("bounty", "difficulty:hard", "bounty:claimed"), []),  # **声明** claimed、账本无 ⇒ 缺账本事件
        (9, ("bounty", "difficulty:hard", "bounty:settled"),
         mk(9, "settled", 10)),                         # 账本 settle ＋ 标记 settled ⇒ 一致
        (10, ("bounty", "difficulty:medium", "bounty:settled"), mk(10, "settled", 8)),  # 只被 covers 覆盖
        (11, ("bounty", "difficulty:medium", "bounty:settled"), mk(11, "settled", 9)),  # 只被 covers 覆盖
    ]
    events = [
        {"ts": "2026-10-12T12:00:00Z", "issue": 1, "action": "claim"},
        {"ts": "2026-10-12T12:00:00Z", "issue": 1, "action": "deliver"},
        {"ts": "2026-10-12T12:00:00Z", "issue": 1, "action": "settle"},
        {"ts": "2026-10-12T13:00:00Z", "issue": 2, "action": "claim"},
        {"ts": "2026-10-12T14:00:00Z", "issue": 2, "action": "settle"},
        {"ts": "2026-10-12T12:00:00Z", "issue": 4, "action": "settle"},
        {"ts": "2026-10-12T12:00:00Z", "issue": 5, "action": "deliver"},
        {"ts": "2026-10-12T15:00:00Z", "issue": 5, "action": "settle"},
        {"ts": "2026-10-12T13:00:00Z", "issue": 9, "action": "claim"},
        {"ts": "2026-10-12T14:00:00Z", "issue": 9, "action": "settle", "covers": [9, 10, 11]},
        {"ts": "2026-10-12T12:00:00Z", "issue": 42, "action": "role", "role": "reviewer"},
        {"ts": "2026-10-12T12:00:00Z", "issue": 43, "action": "reject"},
    ]
    return issues, events


def _run():
    issues, events = _fixture()
    return cp.reconcile([(n, l, c) for n, l, c in issues], events)


# 生效条件：一次性把全部临时夹具建好——**在跑断言之前**（否则断言之间产生顺序依赖：
# 先跑的断言会因为后跑的才写夹具而读不到文件）。
def _ensure_temp_fixtures():
    _write_ok_fixtures()
    _write_state_probe()
    _write_drift_fixtures()


def _verdicts(res):
    return {row[0]: row[3] for row in res["rows"]}


# 生效条件：在 FIXDIR 下写一对**无漂移**夹具（**常量、不派生自被测逻辑**——若派生，变异会让
# 它自己变脏，正反腿就互相污染）；供 `--strict` 的「无漂移 ⇒ 0」正面腿使用。
# 构造成本：三条三面一致的记录（#1 settled / #7 只有入选标记 ⇒ 默认 open / #9 settled）。
_OK_ISSUES = [{"number": 1, "labels": ["bounty", "difficulty:hard", "bounty:settled"],
               "comments": ["<!-- bounty:v1 {\"seq\": 4, \"state\": \"settled\"} -->"]},
              {"number": 7, "labels": ["bounty", "difficulty:expert"], "comments": []},
              {"number": 9, "labels": ["bounty", "difficulty:hard", "bounty:settled"],
               "comments": ["<!-- bounty:v1 {\"seq\": 10, \"state\": \"settled\"} -->"]}]
_OK_EVENTS = [{"ts": "2026-10-12T12:00:00Z", "issue": 1, "action": "settle"},
              {"ts": "2026-10-12T14:00:00Z", "issue": 9, "action": "settle"}]

#: 常量「多类缺陷共存」样本——供 `drift` 布尔腿（--json / --strict 正面腿）用。
#: **故意让缺陷跨类**（态冲突 ＋ 缺标签）：任何**单一**变异都清不空它 ⇒ 布尔腿不会随单变异翻面。
_DRIFT_ISSUES = [(40, ("bounty", "difficulty:hard", "bounty:claimed"),
                  ["<!-- bounty:v1 {\"seq\": 2, \"state\": \"claimed\"} -->"]),
                 (41, ("difficulty:hard"), [])]
_DRIFT_EVENTS = [{"ts": "2026-10-12T12:00:00Z", "issue": 40, "action": "settle"},
                 {"ts": "2026-10-12T13:00:00Z", "issue": 41, "action": "settle"}]


def _drift_result():
    return cp.reconcile([(n, l, c) for n, l, c in _DRIFT_ISSUES], _DRIFT_EVENTS)


def _write_ok_fixtures():
    os.makedirs(FIXDIR, exist_ok=True)
    with open(GOLDEN_OK_ISSUES, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"items": _OK_ISSUES}, fh, ensure_ascii=False, indent=2)
    with open(GOLDEN_OK_LEDGER, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"events": _OK_EVENTS}, fh, ensure_ascii=False, indent=2)
    return [i["number"] for i in _OK_ISSUES]


# 生效条件：写「多类缺陷共存」常量样本到临时夹具（供 --strict 的「检出漂移 ⇒ 1」正面腿走文件路径）。
def _write_drift_fixtures():
    os.makedirs(FIXDIR, exist_ok=True)
    with open(GOLDEN_DRIFT_ISSUES, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"items": [{"number": n, "labels": list(l), "comments": list(c)}
                             for n, l, c in _DRIFT_ISSUES]}, fh, ensure_ascii=False, indent=2)
    with open(GOLDEN_DRIFT_LEDGER, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"events": _DRIFT_EVENTS}, fh, ensure_ascii=False, indent=2)


# 生效条件：写 `--state` 探针到临时夹具（bounty_board 同格式；覆盖一致腿与缺账本事件腿）。
def _write_state_probe():
    os.makedirs(FIXDIR, exist_ok=True)
    with open(GOLDEN_STATE, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(_STATE_PROBE, fh, ensure_ascii=False, indent=2)


def _defects(res):
    return {k: list(v) for k, v in res["defects"].items()}


def run_checks():
    global _red
    _red = []
    _ensure_temp_fixtures()
    res = _run()
    v = _verdicts(res)
    d = _defects(res)
    text = cp.render(res)

    # D1 一致行 + 态优先级
    ok("D1 账本+标签同态 ⇒ 一致", v.get(1) == "一致", v)
    ok("D1b 标记优先于标签（标记 settled / 标签 claimed 不算一致）",
       v.get(2) == cp.DEFECT_STATE_CONFLICT, v)
    ok("D1c 标记 settled ＋ 标签 settled ＋ 账本 settled ⇒ 一致（不误报）",
       v.get(9) == "一致", v)
    ok("D1d **默认 open 不需账本背书**（只有入选标记、无声明态 ⇒ 不算漂移）",
       v.get(7) == "一致", v)

    # D2 态冲突点名
    hits = d[cp.DEFECT_STATE_CONFLICT]
    ok("D2 态冲突点名该 issue", any("#2 " in h and "账本=settled" in h for h in hits), hits)
    ok("D2b 冲突行在表里可见", any(r[0] == 2 and r[3] == cp.DEFECT_STATE_CONFLICT for r in res["rows"]))

    # D3 缺账本事件（**声明态**才要求账本背书：态标签一条 + 标记一条，判据两条腿都有反面）
    hits = d[cp.DEFECT_LEDGER_GAP]
    ok("D3 态标签声明态、账本无 ⇒ 点名缺账本事件",
       any(h.startswith("#8 ") for h in hits), hits)
    ok("D3b 只有标记声明态、账本无 ⇒ 同样点名",
       any(h.startswith("#3 ") for h in hits), hits)
    ok("D3c 默认 open 不进「缺账本事件」（R1 降噪：默认态由标签推导，不需账本背书）",
       not any(h.startswith("#7 ") for h in hits), hits)

    # D4 缺标签（账本有、issue 面无入选标记）
    hits = d[cp.DEFECT_LABEL_GAP]
    ok("D4 账本有事件而 issue 面无 bounty 标签 ⇒ 点名缺标签",
       any("#4 " in h and cp.bb.LABEL_GATE in h for h in hits), hits)

    # D5 covers 覆盖号不代入
    nums = {r[0] for r in res["rows"]}
    ok("D5 covers 覆盖号不进三方表", 10 not in nums and 11 not in nums, sorted(nums))
    ok("D5b covers-覆盖号数在摘要里显式留痕（不静默吞）",
       res["summary"].get("covers_only") == 2, res["summary"])
    ok("D5c covers-覆盖号**列名**（只报个数等于「有号有嫌疑但不说是哪个」）",
       res.get("covers_only_nums") == [10, 11] and "#10" in text and "#11" in text,
       res.get("covers_only_nums"))

    # D6 普通 issue 不代入
    ok("D6 普通 issue 不代入", 6 not in nums, sorted(nums))

    # D12 标记态 ≠ 标签态（标记是权威面）：账本与**标记**对得上 ⇒ 问题出在标签（标签过期/被手改）
    res2 = cp.reconcile([(20, ("bounty", "difficulty:hard", "bounty:claimed"),
                          ["<!-- bounty:v1 {\"seq\": 3, \"state\": \"delivered\"} -->"])],
                        [{"ts": "2026-10-12T12:00:00Z", "issue": 20, "action": "deliver"}])
    ok("D12 账本≡标记、标签不同 ⇒ 点名「标记态冲突」并说清是哪一面",
       res2["rows"][0][3] == cp.DEFECT_MARKER_CONFLICT
       and any("#20 标记态冲突" in h and "标签=claimed" in h
               for h in res2["defects"][cp.DEFECT_MARKER_CONFLICT]),
       res2["defects"][cp.DEFECT_MARKER_CONFLICT])
    ok("D12b 三面一致 ⇒ 一致",
       cp.reconcile([(21, ("bounty", "difficulty:hard", "bounty:settled"),
                      ["<!-- bounty:v1 {\"seq\": 3, \"state\": \"settled\"} -->"])],
                    [{"ts": "2026-10-12T12:00:00Z", "issue": 21, "action": "settle"}])["rows"][0][3] == "一致")
    # D12c 账本≡标记、标签不同 ⇒ 同样应报冲突（权威面与账本一致 ⇒ 过期的是标签）
    r20 = cp.reconcile([(22, ("bounty", "difficulty:hard", "bounty:claimed"),
                         ["<!-- bounty:v1 {\"seq\": 3, \"state\": \"settled\"} -->"])],
                       [{"ts": "2026-10-12T12:00:00Z", "issue": 22, "action": "settle"}])
    ok("D12c 账本≡标记、标签不同 ⇒ 也报冲突（且风格与 D12 一致）",
       r20["rows"][0][3] == cp.DEFECT_MARKER_CONFLICT
       and any("#22 标记态冲突" in h for h in r20["defects"][cp.DEFECT_MARKER_CONFLICT]),
       r20["defects"][cp.DEFECT_MARKER_CONFLICT])
    # 账本与**两面都不符** ⇒ 态冲突（账本本身才是问题那面）
    r21 = cp.reconcile([(23, ("bounty", "difficulty:hard", "bounty:claimed"),
                         ["<!-- bounty:v1 {\"seq\": 3, \"state\": \"delivered\"} -->"])],
                       [{"ts": "2026-10-12T12:00:00Z", "issue": 23, "action": "settle"}])
    ok("D12d 账本与标记、标签都不符 ⇒ 判态冲突（问题在账本那面）",
       r21["rows"][0][3] == cp.DEFECT_STATE_CONFLICT
       and any("标签与标记均与账本不符" in h for h in r21["defects"][cp.DEFECT_STATE_CONFLICT]),
       r21["defects"][cp.DEFECT_STATE_CONFLICT])

    # D13 漂移检测
    ok("D13 has_drift：有缺陷 ⇒ True", cp.has_drift(res) is True)
    ok("D13b has_drift：无缺陷 ⇒ False",
       cp.has_drift(cp.reconcile([(1, ("bounty", "difficulty:hard", "bounty:settled"),
                                  ["<!-- bounty:v1 {\"seq\": 1, \"state\": \"settled\"} -->"])],
                                 [{"ts": "2026-10-12T12:00:00Z", "issue": 1, "action": "settle"}])) is False)

    # D14 --check / --dry-run 两模式退出码（体例对齐 bounty_list.py --check）
    rc, out = cp.core(["--check"])
    ok("D14 --check 用仓内夹具、检出漂移 ⇒ 1", rc == 1 and "[check] 检出漂移" in out, f"rc={rc}")
    ok("D14b --check 数据源是仓内夹具（无网可跑）", "tests\\fixtures" in out or "tests/fixtures" in out, out[:120])
    ok("D14c 缺输入时**响亮失败**（不拿样例冒充仓内实际状态）",
       cp.core(["--dry-run"])[0] == 1 and "[error]" in cp.core(["--dry-run"])[1])
    ok("D14d 用法错 ⇒ 2", cp.core([])[0] == 2)
    ok("D14e 显式坏输入 ⇒ 1", cp.core(["--check", "--issues", "__nope__.json"])[0] == 1)

    # D17 `--state` 离线镜像（原 issue 验收原文点名的输入面：bounty_board 同格式）
    _write_state_probe()
    rc, out = cp.core(["--dry-run", "--state", GOLDEN_STATE])
    ok("D17 --state 镜像可对账（镜像即世界；退出 0；#1/#2 一致）",
       rc == 0 and "| #1 | settled | settled | 一致 |" in out
       and "| #2 | settled | settled | 一致 |" in out, out[:240])
    ok("D17b --state 镜像里的账本腿生效（#8 声明态、账本无 ⇒ 缺账本事件）",
       "#8 缺账本事件" in out, out[:240])
    ok("D17c 镜像读不了 ⇒ 1",
       cp.core(["--dry-run", "--state", "__nope_state.json"])[0] == 1)

    # D15 机读口径（--json；稳定结构供下游自动化消费）
    rc, out = cp.core(["--dry-run", "--json", "--ledger", cp.GOLDEN_LEDGER, "--issues", cp.GOLDEN_ISSUES])
    doc = json.loads(out)
    ok("D15 --json 输出合法 JSON、schema 稳定", rc == 0 and doc["schema"] == "check_plan/v1")
    ok("D15b --json 行与缺陷结构化（稳定键）",
       doc["rows"] and all(set(r) == {"issue", "label_state", "ledger_state", "verdict"}
                           for r in doc["rows"])
       and set(doc["defects"]) == set(cp.DEFECT_ORDER) and "summary" in doc)
    _j = cp.to_json(res)
    ok("D15b2 to_json 带 covers_only_nums / drift",
       _j["covers_only_nums"] == [10, 11] and _j["drift"] is True, _j["covers_only_nums"])
    ok("D15c --json 带 drift 布尔（用跨类缺陷常量样本：单变异清不空它）",
       cp.to_json(_drift_result())["drift"] is True)
    rc, out = cp.core(["--check", "--json"])
    ok("D15d --check --json 也出 JSON（无 [check] 人类尾巴）",
       rc == 1 and json.loads(out)["drift"] is True and "[check]" not in out)

    # D16 准入模式（--strict）：把「检出漂移」映射成非零；默认模式**不**这样
    ok("D16 默认 --dry-run 检出漂移仍为 0（只报自身跑通）",
       cp.core(["--dry-run", "--ledger", GOLDEN_DRIFT_LEDGER, "--issues", GOLDEN_DRIFT_ISSUES])[0] == 0)
    ok("D16b --strict 检出漂移 ⇒ 1（CI 准入用）",
       cp.core(["--dry-run", "--strict", "--ledger", GOLDEN_DRIFT_LEDGER,
                "--issues", GOLDEN_DRIFT_ISSUES])[0] == 1)
    ok("D16c --strict 无漂移 ⇒ 0",
       cp.core(["--dry-run", "--strict", "--ledger", GOLDEN_OK_LEDGER,
                "--issues", GOLDEN_OK_ISSUES])[0] == 0)
    ok("D16d 无漂移输入下 has_drift 为 False",
       cp.has_drift(cp.scan(GOLDEN_OK_LEDGER, GOLDEN_OK_ISSUES)) is False)

    # D7 多态标签（标签面**自身**矛盾，单列一类）
    ok("D7 多态标签自相矛盾要报",
       any("#5 多态标签" in h for h in d[cp.DEFECT_MULTI_LABEL]), d[cp.DEFECT_MULTI_LABEL])
    ok("D7b 多态标签不混进「态冲突」清点",
       not any("多态标签" in h for h in d[cp.DEFECT_STATE_CONFLICT]), d[cp.DEFECT_STATE_CONFLICT])

    # D8 确定性
    ok("D8 确定性（两遍同文本）", cp.render(_run()) == cp.render(_run()))

    # D9 退出码
    with tempfile.TemporaryDirectory() as td:
        led = os.path.join(td, "ledger.json")
        snap = os.path.join(td, "issues.json")
        issues, events = _fixture()
        with open(led, "w", encoding="utf-8") as fh:
            json.dump({"events": events}, fh, ensure_ascii=False)
        with open(snap, "w", encoding="utf-8") as fh:
            json.dump({"items": [{"number": n, "labels": list(l), "comments": list(c)}
                                 for n, l, c in issues]}, fh, ensure_ascii=False)
        rc = cp.main(["--dry-run", "--ledger", led, "--issues", snap])
        ok("D9 有不一致仍退出 0（真问题 ≠ 脚本故障）", rc == 0, f"rc={rc}")
        rc = cp.main(["--dry-run", "--ledger", led, "--issues", os.path.join(td, "nope.json")])
        ok("D9b 快照读不了 ⇒ 1", rc == 1, f"rc={rc}")
        bad = os.path.join(td, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        rc = cp.main(["--dry-run", "--ledger", led, "--issues", bad])
        ok("D9c 坏 JSON ⇒ 1", rc == 1, f"rc={rc}")

    # D10 缺快照不得静默当一致
    ok("D10 缺快照报 ScanError（不静默）",
       _raises_scan(lambda: cp.scan(os.path.join(REPO, "docs", "bounty", "ledger.json"),
                                   os.path.join(REPO, "docs", "bounty", "__nope__.json"))))

    # D11 零第三方依赖 / 不碰计分口径
    src = open(IMPL, encoding="utf-8").read()
    ok("D11 只 import stdlib + 本仓 bounty_board",
       sorted(_imports(src)) == ["argparse", "bounty_board", "json", "os", "sys"], sorted(_imports(src)))
    ok("D11b 不碰计分口径常量",
       not re.search(r"(DIFFICULTY_SCORES|quality_delta|PROMOTION_RULES)\s*=", src))
    ok("D11c 不写账本（无写文件调用）",
       "write_ledger" not in src and "open(.*[\"']w" not in src)
    # 同仓标准：**全仓零第三方依赖**——导出器也要过同一道闸（它在 scripts/ 下，属仓内面）
    src2 = open(os.path.join(SCRIPTS, "check_plan_snapshot.py"), encoding="utf-8").read()
    ok("D11d 导出器同样只 import stdlib",
       sorted(_imports(src2)) == ["argparse", "base64", "json", "os", "re", "subprocess", "sys"],
       sorted(_imports(src2)))


def _raises_scan(fn):
    try:
        fn()
    except cp.ScanError:
        return True
    except Exception:                                    # noqa: BLE001
        return False
    return False


def _imports(src):
    out = set()
    for m in re.finditer(r"^(?:import|from)\s+([A-Za-z_][\w]*)", src, re.M):
        if m.group(1) != "__future__":       # 编译器指令，非依赖
            out.add(m.group(1))
    return out


_MUTATIONS = (
    ("M1 态冲突比较短路（某面与账本矛盾不再被看见）",
     "        if declared and lst and lst != eff:",
     "        if False:  # MUT",
     {"D1b", "D2", "D2b", "D12d"}),
    ("M2 缺标签判据短路（无入选标记也放过）",
     "        elif lst and bb.LABEL_GATE not in labels:",
     "        elif False:  # MUT",
     {"D4"}),
    ("M3 缺账本事件判据短路（声明态、账本查无此号也放过）",
     "        elif declared and not lst:",
     "        elif False:  # MUT",
     {"D3", "D3b", "D17b"}),
    ("M7 标记态冲突判据短路（标签与标记互相矛盾不再被看见）",
     "        elif lst and ls and ms and ls != ms:",
     "        elif False:  # MUT",
     {"D12", "D12c"}),
    ("M4 covers 覆盖号被判成独立悬赏（一次结算覆盖十条 → 十条假缺标签）",
     "    covers_only = cover_nums - ledger_nums",
     "    covers_only = set()  # MUT",
     {"D5", "D5b", "D5c", "D15b2"}),
    ("M5 多态标签不报（标签面自身矛盾被静默）",
     "        if multi:",
     "        if False:  # MUT",
     {"D7"}),
    ("M6 入选标记闸失效（普通 issue 也代入三方表）",
     "        if bb.LABEL_GATE not in labels and num not in ledger_nums:",
     "        if False:  # MUT",
     {"D6"}),
)

#: 变异 → (被测函数名, 跑哪些断言组)
_MUT_TARGETS = (
    ("M1", "reconcile", run_checks),
    ("M2", "reconcile", run_checks),
    ("M3", "reconcile", run_checks),
    ("M4", "reconcile", run_checks),
    ("M5", "reconcile", run_checks),
    ("M6", "reconcile", run_checks),
    ("M7", "reconcile", run_checks),
)


class AnchorMiss(Exception):
    pass


# 生效条件：fn_name 为 check_plan 模块内函数名、old 为唯一锚点、new 为替换文本时，用
# inspect.getsource 取该函数源码，就地 exec 到模块全局（运行中的实现被替换），返回复原函数；
# 锚点命中次数 ≠1 抛 AnchorMiss（调用方记 ANCHOR-MISS）。
def _mut_source(fn_name, old, new):
    orig = getattr(cp, fn_name)
    src = inspect.getsource(orig)
    if src.count(old) != 1:
        raise AnchorMiss(f"{fn_name}: 锚点命中 {src.count(old)} 次（期望 1）：{old!r}")
    exec(compile(src.replace(old, new), f"<check-plan-{fn_name}-mut>", "exec"), vars(cp))

    def _restore():
        setattr(cp, fn_name, orig)
    return _restore


def _mutate_mode():
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


def _cleanup_temp_fixtures():
    """跑完删掉临时夹具（`__*.json`）——仓里只留 golden 两件，不留运行残渣。"""
    for p in (GOLDEN_OK_ISSUES, GOLDEN_OK_LEDGER, GOLDEN_DRIFT_ISSUES, GOLDEN_DRIFT_LEDGER,
              GOLDEN_STATE):
        try:
            os.remove(p)
        except OSError:
            pass


def main(argv=None):
    global _red
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--list" in argv:
        for name, _o, _n, exp in _MUTATIONS:
            print(f"  {name} → 期望转红 {sorted(exp)}")
        return 0
    if "--mutate" in argv:
        try:
            return _mutate_mode()
        finally:
            _cleanup_temp_fixtures()
    print("=== test_check_plan 正向断言 ===")
    run_checks()
    print(f"\n  失败 {len(_red)}")
    _cleanup_temp_fixtures()
    if _red:
        print(f"  失败项：{sorted(set(_red))}")
        return 1
    print("  ALL OK（反面证明见 --mutate）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
