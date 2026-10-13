# -*- coding: utf-8 -*-
"""check_plan —— 悬赏三方对账校验件（issue 标签面 × 标记面 × 账本面）。

对齐《悬赏与项目管理 v0.2》§二–§五。**纯 stdlib、零网络**：只读
`docs/bounty/ledger.json` 与一份 issue 快照（`--issues`），把两处记录放到一张表上对照，
把漂移**逐条点名**（缺标签 / 缺账本事件 / 态冲突 / 标记态冲突 / 多态标签，各自一行，
不汇总、不静默）。

为什么需要它：标签态是人眼视图、可被手改；标记态是权威面；账本态是机器写的——但此前
**没有任何一件东西同时读它们** ⇒ 漂移只能靠人工盘点发现。

与状态机同尺子：态优先级 `标记 > 标签 > 默认 open`、态标签取值集、动作→态映射，
均**不重新定义**，直接从 `bounty_board` 借用（改口径只改那里）。

判据要点（口径真源见 v0.2 §三）：
  · **默认 open 不需账本背书**：只有 `bounty` 入选标记、没有态标签也没有标记时，态是
    「推导出来的 open」而非「声明态」——它不产生漂移。只有**声明态**（态标签或标记）
    才要求账本有对应事件。
  · **标记是权威面，且参与对账**：标记态与标签态不一致本身就要点名（手工伪造标记的痕迹）。
  · **covers 覆盖号不进三方表但逐个列名**：它们没有独立账本事件；只报个数等于
    「有号有嫌疑但不说是哪个」。

退出码（见 v0.2 §四 / §五）：
  `--dry-run`：0 = 校验件自身跑通（**含「有不一致」的情形**——真问题不是脚本故障）；
               1 = 账本/快照读不了（结构坏、缺文件而显式指定）；2 = 用法错。
  `--check`  ：本仓固定输入的**漂移检测**（体例对齐 `scripts/bounty_list.py --check`）；
               0 = 无漂移，1 = 检出漂移或输入坏。默认数据源是仓内固定夹具
               `tests/fixtures/check_plan_golden.json`（**无网可跑**）。

用法：
  python -X utf8 scripts/check_plan.py --dry-run
  python -X utf8 scripts/check_plan.py --dry-run --issues <快照.json>
  python -X utf8 scripts/check_plan.py --check
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import bounty_board as bb                                              # noqa: E402

DEFAULT_LEDGER = os.path.join(REPO, "docs", "bounty", "ledger.json")
DEFAULT_SNAPSHOT = os.path.join(REPO, "docs", "bounty", "issues-state.json")
GOLDEN_DIR = os.path.join(REPO, "tests", "fixtures")
GOLDEN_ISSUES = os.path.join(GOLDEN_DIR, "check_plan_golden.json")
GOLDEN_LEDGER = os.path.join(GOLDEN_DIR, "check_plan_golden_ledger.json")

#: 账本 action → 它**通常**迁到的态。★**仅作兼容回落**：`bounty_board._accept` 在每条
#: 通过事件里都会写死 `from`/`to`，那份 `to` 才是真源 —— 同一个 action 的目标态**可以不同**：
#: `/verify pass` ⇒ `verified`，而 `/verify fail` ⇒ **`claimed`**（退回返工，见
#: `bounty_board._do_verify`）；`/deliver` 轮次用尽 ⇒ `disputed`。
#: 旧实现**无条件**用本表反推 ⇒ 一次正常的 `/verify fail` 会被判成 `verified`，
#: 与标签/标记的 `claimed` 对不上 ⇒ **假「态冲突」**。
#: 本表只在事件**不含 `to`** 时使用（历史遗留：维护者的批量补记件不走 `_accept`，故无 `to`）。
#: `reject`/`role` 不改态——拒绝是尝试痕、role 是授权面。
LEDGER_TO_STATE = {
    "claim": "claimed",
    "deliver": "delivered",
    "verify": "verified",
    "settle": "settled",
    "withdraw": "open",
    "dispute": "disputed",
    "expire": "expired",
}
NO_STATE_ACTIONS = ("reject", "role")   # 文档用：这两类不态迁移（判据在 LEDGER_TO_STATE）


# 生效条件：ev 为账本事件 dict 时返回它迁到的态（可能为空串）——
# **优先取事件自带的 `to`**（真源，随结果变化），无 `to` 时回落到 `LEDGER_TO_STATE`（兼容）。
def state_of_event(ev) -> str:
    """事件迁到的态：`to` 优先，动作表回落。**两者皆无 ⇒ 空串**（调用方据此跳过）。"""
    to = str(ev.get("to") or "")
    if to:
        return to
    return LEDGER_TO_STATE.get(str(ev.get("action") or "")) or ""

DEFECT_LABEL_GAP = "缺标签"
DEFECT_LEDGER_GAP = "缺账本事件"
DEFECT_STATE_CONFLICT = "态冲突"
#: 标记态是**权威面**，与标签态不一致 ⇒ 标签是人眼视图过期（或标记被手写）。
DEFECT_MARKER_CONFLICT = "标记态冲突"
#: 标签面**自身**矛盾（多个 `bounty:*` 态标签并存）——不是两面冲突，单列一类不混报。
DEFECT_MULTI_LABEL = "多态标签"
DEFECT_ORDER = (DEFECT_LABEL_GAP, DEFECT_LEDGER_GAP, DEFECT_STATE_CONFLICT,
                DEFECT_MARKER_CONFLICT, DEFECT_MULTI_LABEL)


class ScanError(Exception):
    """校验件自身的输入问题（账本/快照读不了）——不是被检出的不一致。"""


# ================================================================ 读取面


# 生效条件：path 为 JSON 文件路径时读取并返回文档；文件不存在抛 ScanError（**不静默当空**）。
def read_json(path):
    if not os.path.isfile(path):
        raise ScanError(f"文件不存在：{path}")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as exc:
        raise ScanError(f"不是合法 JSON：{path}（{exc}）") from exc


# 生效条件：path 为账本 JSON 路径时返回事件列表；**文件不存在抛 ScanError**。
# ★本笔：**不能**直接调 `bb.load_ledger` —— 它对不存在的路径返回 `[]`（那是「离线演练
# 起点」语义，见 `bounty_board.load_ledger` 的说明）。对被**显式指定**的审计对象，
# 这个语义是错的：会把「账本文件根本不在」伪装成「账本里一条事件都没有」，于是
# 每个号都被判「缺账本事件」、整批假阳性，而且**退出码 0**（本件 docstring 承诺
# 「1 = 账本/快照读不了（结构坏、缺文件而显式指定）」）。
# **快照腿与镜像腿都做了这道检查**（`read_json` 先 `isfile`；`read_state` 同），唯独账本腿漏了。
def read_ledger(path):
    if not os.path.isfile(path):
        raise ScanError(f"文件不存在：{path}")
    return bb.load_ledger(path)


# 生效条件：obj 为快照文档（{"items": [...]} 或裸列表）时归一化为 [(number, labels, comments)] 升序去重；
# 字段形状不符抛 ScanError（坏输入不静默跳过）。
def normalize_issues(obj):
    items = obj.get("items") if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        raise ScanError("快照结构不符（须为 {'items': [...]} 或裸列表）")
    out = {}
    for i, rec in enumerate(items):
        if not isinstance(rec, dict):
            raise ScanError(f"快照第 {i} 项不是对象")
        try:
            num = int(rec.get("number"))
        except (TypeError, ValueError):
            raise ScanError(f"快照第 {i} 项 number 缺失/非整数") from None
        labels = rec.get("labels") or ()
        comments = rec.get("comments") or ()
        if not isinstance(labels, (list, tuple)) or not isinstance(comments, (list, tuple)):
            raise ScanError(f"快照 #{num} 的 labels/comments 须为列表")
        out[num] = (num, tuple(str(x) for x in labels), tuple(str(x) for x in comments))
    return [out[k] for k in sorted(out)]


# ================================================================ 三方派生


# 生效条件：labels 为标签元组时返回 (裸态名, 多态标记)——按 STATE_LABELS 声明序取第一个命中的态标签。
# 「多态标签」描述的是标签面自身矛盾（人眼视图种出来的），不是两面冲突。
def label_state_of(labels):
    hits = [lbl for lbl in bb.STATE_LABELS if lbl in labels]
    if not hits:
        return "", False
    return hits[0].split(":", 1)[1], len(hits) > 1


# 生效条件：comments 为评论正文元组时返回最新标记 dict（seq 最大者；坏 JSON 跳过）；无合格标记返回 {}。
# 与 bb.latest_marker 同序（`>=` ⇒ 同 seq 取靠后者）。
def marker_of(comments):
    best = None
    for body in comments or ():
        for m in bb.MARKER_RE.finditer(body or ""):
            try:
                rec = json.loads(m.group(1))
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("state"):
                if best is None or bb._seq(rec) >= bb._seq(best):
                    best = rec
    return best or {}


# 生效条件：labels/comments 给定时返回 (有效态, 标签态, 标记态, 多态标记, 是否声明态)——
# 与 bb.build_state 同优先级「标记 > 标签 > （有 bounty 标签则 open）」；`declared` 表示该态是
# **声明**出来的（态标签或标记）而不是只由 `bounty` 推导的默认 open——只有声明态要求账本背书。
def states_of(labels, comments):
    ls, multi = label_state_of(labels)
    ms = str(marker_of(comments).get("state") or "")
    eff = ms or ls or ("open" if bb.LABEL_GATE in labels else "")
    declared = bool(ls or ms)
    return eff, ls, ms, multi, declared


# 生效条件：events 为账本事件列表、primary 为「真的作为 issue 出现过」的号集合时返回 {号: 态}——
# 按 (ts, 追加序) 取该号最后一次态迁移；**只给 primary 补 covers 扩展**（covers-only 号没有
# 自己的事件，若也发事件就会污染「该号有没有账本记录」的判定）。
def ledger_states(events, primary=None):
    # ★本笔：排序键对**非对象元素**做防护。旧实现 `(p[1] or {}).get("ts")` ——
    # `p[1]` 非空但不是 dict（如手工改坏的账本里塞了字符串）⇒ `str.get` ⇒
    # **未捕获 `AttributeError`**，`core()` 直接抛，而不是走 `ScanError`。
    # 同函数下方多处已 `isinstance(ev, dict)`，**唯独排序键漏了** ——
    # 即「过滤在循环里、取键在循环外」的典型漏点。
    ordered = sorted(
        enumerate(events or ()),
        key=lambda p: (str((p[1] or {}).get("ts") or "")
                       if isinstance(p[1], dict) else "", p[0]),
    )
    out = {}
    for _i, ev in ordered:
        if not isinstance(ev, dict):
            continue
        # ★本笔：`to` 优先（真源）——旧实现无条件用 `LEDGER_TO_STATE` 反推，会把
        # `/verify fail`（`to=claimed`）误判成 `verified` ⇒ 假「态冲突」。
        to = state_of_event(ev)
        if not to:
            continue
        nums = [ev.get("issue")]
        cov = ev.get("covers")
        if isinstance(cov, (list, tuple)):
            for n in cov:
                try:
                    ni = int(n)
                except (TypeError, ValueError):
                    continue
                if primary is None or ni in primary:
                    nums.append(ni)
        for n in nums:
            try:
                out[int(n)] = to
            except (TypeError, ValueError):
                continue
    return out


# 生效条件：events 为账本事件列表时返回「有**态迁移**事件、真的作为 issue 出现过」的号集合——
# `role`/`reject` 不改态，不算数（否则纯授权/拒绝记录会被误报成悬赏）。
def ledger_issue_numbers(events):
    out = set()
    for ev in events or ():
        if not isinstance(ev, dict):
            continue
        # ★本笔：与 `ledger_states` 同一判据（`to` 优先 + 动作表回落）——两处必须同尺子，
        # 否则「有态迁移的号」集合与「态表」的键集会对不上。
        if not state_of_event(ev):
            continue
        raw = ev.get("issue")
        s = str(raw if raw is not None else "")
        if s.lstrip("-").isdigit():
            out.add(int(raw))
    return out


def _cover_numbers(events):
    """返回 (全部 covers 覆盖号, 只被 covers 覆盖的号)。"""
    cover = set()
    for ev in events or ():
        if isinstance(ev, dict) and isinstance(ev.get("covers"), (list, tuple)):
            for n in ev["covers"]:
                try:
                    cover.add(int(n))
                except (TypeError, ValueError):
                    continue
    return cover


# 生效条件：store 为离线状态镜像（bounty_board 的 --state 格式）时返回 [(number, labels, comments)]
# ——镜像里 `markers` 存的是**已解析的标记字典**（不是评论文本），故这里把每个标记重新渲染成
# `<!-- bounty:v1 {...} -->` 文本，好让对账走同一条标记解析路径（**单一真源**）。
def issues_from_store(store):
    out = []
    for key, rec in sorted((store.get("issues") or {}).items(),
                           key=lambda kv: int(kv[0]) if str(kv[0]).lstrip("-").isdigit() else 0):
        if not isinstance(rec, dict):
            continue
        try:
            num = int(rec.get("number") if rec.get("number") is not None else key)
        except (TypeError, ValueError):
            continue
        comments = []
        for mk in rec.get("markers") or ():
            if isinstance(mk, dict):
                comments.append("<!-- bounty:v1 " + json.dumps(mk, ensure_ascii=False) + " -->")
            elif isinstance(mk, str):
                comments.append(mk)
        out.append((num, tuple(str(x) for x in (rec.get("labels") or ())), tuple(comments)))
    return out


def read_state(path):
    """读 --state 镜像（bounty_board.load_store 的同一格式）。

    ★ 这里**先查文件在不在**：`bounty_board.load_store` 对不存在的路径返回**空镜像**（它的
    设计是「本地演练起点」），但对账件不能照抄那个语义——「用户显式指定了镜像却读不到」与
    「镜像本来就是空的」是两件事，混起来会把「没数据」报成「无漂移」。
    """
    if not os.path.isfile(path):
        raise ScanError(f"状态镜像不存在：{path}（显式指定的输入必须读得到）")
    try:
        store = bb.load_store(path)
    except bb.BoardError as exc:
        raise ScanError(str(exc)) from exc
    # ★本笔：**形状判据**。`load_store` 只保证「文件在、是 JSON」，**不保证顶层是对象、
    # 更不保证 `issues` 是对象** —— 旧实现直接把 `store.get("issues") or {}` 拿去 `.items()`，
    # 遇到 `{"issues": 5}`（**合法 JSON**）⇒ `AttributeError: 'int' object has no attribute
    # 'items'`，`core()` 直接抛而不是返回退出码，而本件 docstring 承诺
    # 「1 = 账本/快照读不了（**结构坏**、缺文件而显式指定）」。
    if not isinstance(store, dict):
        raise ScanError("状态镜像顶层不是对象：%s（实为 %s）" % (path, type(store).__name__))
    if store.get("issues") is not None and not isinstance(store["issues"], dict):
        raise ScanError("状态镜像的 issues 不是对象：%s（实为 %s）"
                        % (path, type(store["issues"]).__name__))
    if store.get("ledger") is not None and not isinstance(store["ledger"], (list, tuple)):
        raise ScanError("状态镜像的 ledger 不是数组：%s（实为 %s）"
                        % (path, type(store["ledger"]).__name__))
    return issues_from_store(store), list(store.get("ledger") or [])


# ================================================================ 对账面


# 生效条件：issues 为 [(number, labels, comments)]、events 为账本事件列表时返回
# {"rows": [...], "defects": {各类: [行]}, "summary": {...}, "covers_only_nums": [...]}
# ——各类缺陷各自点名，互不吞并。
def reconcile(issues, events):
    #: 真的作为账本 `issue` 出现过、且带态迁移的号（covers-only / role / reject 不算）。
    ledger_nums = ledger_issue_numbers(events)
    lstates = ledger_states(events, primary=ledger_nums)
    cover_nums = _cover_numbers(events)
    covers_only = cover_nums - ledger_nums
    rows, defects = [], {cls: [] for cls in DEFECT_ORDER}
    scanned = set()
    # 代入三方表的号 = 快照号 ∪ 账本号；**只被 covers 覆盖的号不代入第三方表**（它们没有独立
    # 的账本事件，逐号追责会把「一次结算覆盖十条」误报成十条缺标签），但会在摘要里逐个列名。
    snap = {n: (l, c) for n, l, c in issues}
    items = []
    for num in sorted(set(snap) | ledger_nums):
        if num in covers_only:
            continue
        labels, comments = snap.get(num, ((), ()))
        # 普通 issue 不代入：既无 bounty 入选标记、也不在账本里。
        if bb.LABEL_GATE not in labels and num not in ledger_nums:
            continue
        items.append((num, labels, comments))
    for num, labels, comments in items:
        eff, ls, ms, multi, declared = states_of(labels, comments)
        lst = lstates.get(num, "")
        scanned.add(num)
        # 语义优先级：**两面互相矛盾**（态冲突 / 标记态冲突）优先于**单面缺件**（缺标签 / 缺账本事件）
        # ——矛盾更严重，且先报矛盾才不会被「缺件」把话抢走。
        # 口径：有**声明态**（态标签或标记）就要求账本有对应事件；只有 `bounty` 推导出的默认 open
        # 才不需账本背书（否则线上每个刚挂上的 `bounty:open` 都会炸成漂移）。
        verdict = "一致"
        broken = ""
        # ★本笔：**去掉 `declared` 合取项** —— 它吞掉了「账本声明了态、issue 面一个态都没声明」
        # 这一方向。旧判据只校验「声明态 ⇒ 账本」，不校验「账本有态 ⇒ issue 面须声明」。
        # 例：`#76` 标签 `open`（仅由 `bounty` 推导，`declared=False`）、账本 `settled`
        # ⇒ 旧实现判「一致」（漏报），而 v0.2 §三优先 1 的判据原文是
        # 「账本与有效态不一致，**且账本与标记、标签两面都对不上**」—— #76 完全命中。
        # `declared` 对其既定目的（「默认 open 不需账本背书」）是**冗余**的：
        # 那种情形下 `lst` 为空，`lst and …` 已短路。
        if lst and lst != eff:
            verdict = DEFECT_STATE_CONFLICT
            # 账本与「标签/标记合成的有效态」对不上 ⇒ 说清**是哪一面**与账本矛盾，好定位。
            if ls and lst == ls:
                broken = f"标记态与账本不符（标记={ms}）"
            elif ms and lst == ms:
                broken = f"标签态与账本不符（标签={ls}）"
            else:
                broken = "标签与标记均与账本不符"
        # ★本笔：把 `difficulty:*` 的缺件判据从**串联**改成**并联**。
        # 旧实现：verdict 只在「缺 `bounty`」时才落到 `DEFECT_LABEL_GAP`，
        # 而下方 `if not any(lbl.startswith("difficulty:"))` 那一支**永远不可达**
        # （L352 的 `if bb.LABEL_GATE not in labels` 必然为真时才走到这里）。
        # ⇒ 「已结算、却从未定难度」这一缺口**零判据**，而 `_do_settle` 对无 difficulty 的
        # 悬赏**照常结算**（只写「无 difficulty 标签（按 base 1 记）」）⇒ 该形态是**正常产物**。
        # v0.2 §三优先 2 的判据是「账本有事件 **且**（无 `bounty` **或** 无 `difficulty`）」
        # —— **每缺一项一行**，两个条件本应并列。
        elif lst and (bb.LABEL_GATE not in labels
                      or not any(lbl.startswith("difficulty:") for lbl in labels)):
            verdict = DEFECT_LABEL_GAP          # 账本有事件，issue 面缺入选标记或难度标签
        elif declared and not lst:
            verdict = DEFECT_LEDGER_GAP         # 有声明态却账本查无此号
        elif lst and ls and ms and ls != ms:
            # 到这儿说明 led → 有效态 已经对上了，但标签与标记**互相矛盾**（手工伪造标记的痕迹）
            verdict = DEFECT_MARKER_CONFLICT
            broken = f"标记={ms} 标签={ls}"
        rows.append((num, eff or "-", lst or "-", verdict))
        if verdict == DEFECT_STATE_CONFLICT:
            defects[verdict].append(
                f"#{num} 态冲突：标签/标记={eff or '-'} 账本={lst}（{broken}）")
        elif verdict == DEFECT_LEDGER_GAP:
            defects[verdict].append(f"#{num} 缺账本事件：声明态={eff or '-'}（账本查无此号）")
        elif verdict == DEFECT_LABEL_GAP:
            if bb.LABEL_GATE not in labels:
                defects[verdict].append(f"#{num} 缺标签：{bb.LABEL_GATE}（账本态={lst or '-'}）")
            if not any(lbl.startswith("difficulty:") for lbl in labels):
                defects[verdict].append(f"#{num} 缺标签：difficulty:*（账本态={lst or '-'}）")
        elif verdict == DEFECT_MARKER_CONFLICT:
            defects[verdict].append(
                f"#{num} 标记态冲突：{broken}"
                f"（账本与有效态已对得上 ⇒ 是标签过期或标记被手写，两种都要人看）")
        if multi:
            defects[DEFECT_MULTI_LABEL].append(
                f"#{num} 多态标签：{'/'.join(sorted(l for l in labels if l in bb.STATE_LABELS))}"
                f"（标签面自身矛盾；有效态取声明序第一个={ls or '-'}）")
    # 账本有、快照完全没这个号 ⇒ 缺标签（issue 面上看不到它，标签无从谈起）；逐号补一行痕。
    for num, st in sorted(lstates.items()):
        if num in snap or num in covers_only:
            continue
        defects[DEFECT_LABEL_GAP].append(f"#{num} 缺标签：{bb.LABEL_GATE}（账本态={st}；快照无此号）")
    summary = {"issues": len(rows),
               "consistent": sum(1 for r in rows if r[3] == "一致")}
    for cls in DEFECT_ORDER:
        summary[cls] = len(defects[cls])
    if cover_nums:
        summary["covers_only"] = len(covers_only)
    return {"rows": rows, "defects": defects, "summary": summary,
            "covers_only_nums": sorted(covers_only)}


# 生效条件：reconcile 的返回值给定时渲染对账文本——表在前、各类点名在后，逐行可 grep。
def render(result):
    rows = result["rows"]
    defects = result["defects"]
    s = result["summary"]
    lines = [
        "| issue | 标签态 | 账本态 | 是否一致 |",
        "|---|---|---|---|",
    ]
    for num, eff, lst, verdict in rows:
        lines.append(f"| #{num} | {eff} | {lst} | {verdict} |")
    if not rows:
        lines.append("| — | — | — | （无悬赏面对账对象） |")
    tail = " ｜ ".join(f"{cls} {s.get(cls, 0)}" for cls in DEFECT_ORDER)
    lines += [
        "",
        f"对账 {s['issues']} 项 ｜ 一致 {s['consistent']} ｜ {tail}"
        + (f" ｜ covers-覆盖号 {s['covers_only']}（未代入表，见下列名）" if s.get("covers_only") else ""),
        "",
    ]
    if result.get("covers_only_nums"):
        # covers 覆盖号不进三方表（它们没有独立的账本事件），但**必须列名**——
        # 只报个数等于「1 个号有嫌疑，但我不告诉你是哪个」，那不是可复盘的点名。
        lines.append("covers-覆盖号（未代入表）："
                     + " ".join(f"#{n}" for n in result["covers_only_nums"]))
        lines.append("")
    for cls in DEFECT_ORDER:
        hits = defects.get(cls) or []
        lines.append(f"## {cls}（{len(hits)}）")
        lines.extend(f"- {x}" for x in hits) if hits else lines.append("- （无）")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# 生效条件：result 给定时返回「是否检出漂移」——只看各类**不一致**计数，不含 covers 覆盖号数。
def has_drift(result):
    return any(len(result["defects"].get(cls) or ()) for cls in DEFECT_ORDER)


# 生效条件：result 给定时返回**机读口径**（稳定结构，供下游自动化消费；schema 见 v0.2 §七）。
def to_json(result):
    s = result["summary"]
    return {
        "schema": "check_plan/v1",
        "rows": [{"issue": n, "label_state": e, "ledger_state": l, "verdict": v}
                 for n, e, l, v in result["rows"]],
        "defects": {cls: list(result["defects"].get(cls) or ()) for cls in DEFECT_ORDER},
        "summary": {k: s[k] for k in s},
        "covers_only_nums": list(result.get("covers_only_nums") or []),
        "drift": has_drift(result),
    }


def render_json(result):
    return json.dumps(to_json(result), ensure_ascii=False, indent=2) + "\n"


# ================================================================ 编排面


# 生效条件：ledger_path/issues_path 给定时返回 reconcile 结果；读不了抛 ScanError。
def scan(ledger_path, issues_path):
    events = read_ledger(ledger_path)
    issues = normalize_issues(read_json(issues_path))
    return reconcile(issues, events)


def core(argv=None):
    """渲染结果并返回 exit_code（供 main / 测试复用）。

    模式：`--dry-run`（全表报告）／`--check`（漂移检测；固定夹具）／`--strict` × `--dry-run`
    （准入：检出漂移即 1）。输入源四选一：`--state`（离线镜像，bounty_board 同格式）／
    `--issues` 快照 ＋ `--ledger` 账本（两者都显式给才算一源）／缺省（`docs/bounty/issues-state.json`
    ＋ `docs/bounty/ledger.json`）。**读不到就响亮失败（1），绝不用内建样例冒充仓内实际状态。**
    """
    args = _parse(argv)
    if args is None:
        return 2, ""
    if not args.dry_run and not args.check:
        return 2, ("用法：check_plan.py --dry-run [--strict] [--json] "
                   "[--state <镜像> | --ledger <p> --issues <p>] ｜ --check\n")
    if args.check:
        # 漂移检测：输入坏或检出漂移 ⇒ 1（体例对齐 bounty_list.py --check）。**默认走仓内固定夹具**
        # （无网可跑）；只有用户显式给了输入源才覆盖——不能拿「线上快照没导出」当漂移。
        src, payload = _pick_source(args, default_golden=True)
    else:
        src, payload = _pick_source(args)
    try:
        if src == "state":
            issues, events = read_state(payload)
        else:
            events = read_ledger(payload[0])
            issues = normalize_issues(read_json(payload[1]))
        result = reconcile(issues, events)
    except ScanError as exc:
        return 1, f"[error] {exc}\n"
    except bb.BoardError as exc:
        return 1, f"[error] 账本/镜像读不了：{exc}\n"
    head = "" if args.json else (
        f"[source] state={payload}\n" if src == "state"
        else f"[source] ledger={payload[0]} ｜ issues={payload[1]}\n")
    body = render_json(result) if args.json else render(result)
    if args.check:
        tail = "" if args.json else ("[check] 检出漂移（见上列点名）\n" if has_drift(result) else "[check] 无漂移\n")
        return (1 if has_drift(result) else 0), head + body + tail
    # `--strict`：把「检出漂移」映射成非零（供 CI 准入用）；**默认不这样**——默认退出码只报
    # 「校验件自身跑通没有」，否则 CI 分不清「脚本坏了」与「真检出漂移」。
    if args.strict and has_drift(result):
        tail = "" if args.json else "[strict] 检出漂移 ⇒ 退出 1（准入模式）\n"
        return 1, head + body + tail
    return 0, head + body


# 生效条件：args 由 _parse 产出时返回 (源类型, 载荷)——"state" ⇒ 镜像路径；"files" ⇒ (账本, 快照)。
# default_golden=True（--check）时，用户没显式给输入就用仓内夹具；否则用缺省真源路径。
def _pick_source(args, default_golden=False):
    if args._exc.get("state"):
        return "state", args.state
    if args._exc.get("issues") or args._exc.get("ledger"):
        return "files", (args.ledger, args.issues)
    if default_golden:
        return "files", (GOLDEN_LEDGER, GOLDEN_ISSUES)
    return "files", (args.ledger, args.issues)


def _parse(argv):
    ap = argparse.ArgumentParser(
        prog="check_plan.py", description="悬赏三方对账：issue 标签面 × 标记面 × 账本面（只读；不触网）")
    ap.add_argument("--dry-run", action="store_true", help="离线对账并打印全表")
    ap.add_argument("--check", action="store_true",
                    help="漂移检测：0=无漂移 / 1=检出漂移或输入坏（默认数据源=仓内夹具）")
    ap.add_argument("--strict", action="store_true",
                    help="准入模式：配合 --dry-run，检出漂移即退出 1（CI 用；默认只报自身跑通）")
    ap.add_argument("--json", action="store_true", help="产物换成机读 JSON（schema=check_plan/v1）")
    ap.add_argument("--state", default=None,
                    help="离线状态镜像（bounty_board 同格式：issues{}/ledger[]；**镜像即世界**）")
    ap.add_argument("--ledger", default=None, help="账本路径（与 --issues 成对）")
    ap.add_argument("--issues", default=None, help="issue 快照路径（与 --ledger 成对）")
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv))
    #: 记住「用户是否显式给了」——`--check` 要靠它区分「用仓内夹具」与「用给定输入」。
    args._exc = {"state": args.state is not None, "ledger": args.ledger is not None,
                 "issues": args.issues is not None}
    if args.ledger is None:
        args.ledger = DEFAULT_LEDGER
    if args.issues is None:
        args.issues = DEFAULT_SNAPSHOT
    return args


def main(argv=None):
    code, text = core(argv)
    if text:
        stream = sys.stderr if code == 2 else sys.stdout
        stream.write(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
