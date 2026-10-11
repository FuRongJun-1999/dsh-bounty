# -*- coding: utf-8 -*-
"""test_bounty_board —— 悬赏板状态机守卫（断言 ＋ 定点变异自证）。

对象：`scripts/bounty_board.py`（**纯逻辑层**——零 IO、零网络，可直接喂夹具）。
设计稿：`docs/spec/悬赏板设计_v0.1.md`；对外规则：`docs/bounty/README.md`。

为什么另立本件：workflow（`.github/workflows/bounty.yml`）只做事件路由，状态机全在
`bounty_board.py`；而悬赏板的**每条校验都是「拒谁于门外」的判据**——判据不设反面
证明就等于没有判据（本仓惯例：注入必红——把判据短路，断言必转红并点名）。
故本件 = ①逐条正反断言 ＋ ②每条校验一个**定点变异**（把该判据短路 ⇒ 对应断言
**必然转红**且**恰好**转红，多红=断言语义纠缠、少红=判据空转）。

本件位置＝`tests/`（与 `scripts/bounty_board.py` 同仓不同目录）：导入靠本文件顶部
把 `scripts/` 插入 `sys.path`——**不依赖任何仓外路径/模块**（本仓独立可跑）。

断言组（与 workflow / README 的口径一一对应）：
  [0] 命令解析：只认「命令在最前、行首」的词
  [A] R3 · 入选标记与态（`bounty` 标签在 ∧ 态 ∈ {open, expired}）
  [B] R1 · 无当前持有者
  [C] R2 · 并发认领上限（默认 2，可配）
  [D] R4 · 仅认领人可交付 / 释放
  [E] R5 · 交付必须带链接或证据块
  [F] 生命周期与账本（验收/结算/轮次上限/超时回板/幂等/荣誉榜）
  [G] 离线两模式自证（`--dry-run` 与 `--state` 真跑子进程）

用法：
  python -X utf8 tests/test_bounty_board.py            # 正向：全断言
  python -X utf8 tests/test_bounty_board.py --mutate   # 定点变异自证（逐条必红）
  python -X utf8 tests/test_bounty_board.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中期望红项；1 = 有断言失败 / 变异未按预期转红；
        2 = ANCHOR-MISS（变异锚点在实现里命中次数 ≠1——实现漂移即硬失败）。
"""
from __future__ import annotations

import inspect
import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))          # <仓根>/tests
REPO = os.path.dirname(HERE)                               # <仓根>
SCRIPTS = os.path.join(REPO, "scripts")                    # 被测件所在目录
sys.path.insert(0, SCRIPTS)

import bounty_board as bb                                            # noqa: E402

IMPL = os.path.join(SCRIPTS, "bounty_board.py")
NOW = bb.parse_ts("2026-10-09T00:00:00Z")
CFG = bb.Config()

PASS = 0
FAIL = 0
FAILS = []


def ok(name, cond, detail=""):
    """逐条记账：`[PASS]` / `[FAIL] name · detail`（同仓 scripts/test_*.py 体例）。"""
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


# 生效条件：给定期望字段缺省时造一个 IssueState 夹具（缺省 = 已入选、开放认领的
# medium 悬赏，作者=维护者）；labels 显式传入时按其构造 includes/has_bounty 两面。
def mk_state(number=101, state="open", holder=None, due=None, rounds=0,
             labels=None, author="FuRongJun-1999", difficulty="difficulty:medium"):
    if labels is None:
        labels = ["bounty", f"bounty:{state}"] + ([difficulty] if difficulty else [])
    return bb.IssueState(number=number, labels=tuple(labels),
                         has_bounty="bounty" in labels, state=state, holder=holder,
                         due_at=due, rounds=rounds, seq=1, difficulty=difficulty,
                         author=author)


# 生效条件：give 为 claim 的附加参数映射时返回该次 /claim 的裁决（actor 缺省 alice）。
def claim(st, actor="alice", active=0, cfg=None):
    return bb.handle_command(st, "/claim", "", "/claim", actor, NOW, cfg or CFG,
                             active_claims=active)


# 生效条件：give 为 deliver 的载荷/正文时返回该次 /deliver 的裁决。
def deliver(st, actor="alice", payload="https://example.com/pull/7", body=None):
    return bb.handle_command(st, "/deliver", payload,
                             body if body is not None else f"/deliver {payload}",
                             actor, NOW, CFG)


# 生效条件：give 为维护者动作参数时返回 /verify 或 /settle 的裁决。
def verify(st, actor="FuRongJun-1999", payload="pass 读数齐全", maint=True):
    return bb.handle_command(st, "/verify", payload, f"/verify {payload}", actor,
                             NOW, CFG, is_maintainer=maint)


def settle(st, actor="FuRongJun-1999", maint=True):
    return bb.handle_command(st, "/settle", "", "/settle", actor, NOW, CFG,
                             is_maintainer=maint)


# ================================================================ [0] 命令解析

def group_parse():
    print("[0] 命令解析：只认「命令在最前、行首」的词")
    c, p = bb.parse_command("/claim")
    ok("A1 行首 /claim 被识别", c == "/claim" and p == "", (c, p))
    c, _p = bb.parse_command("我先看看\n第三行 /claim 一下")
    ok("A2 正文中间出现的命令不认（首行非命令即整条忽略）", c is None, c)
    c, _p = bb.parse_command("claim 我想认领")
    ok("A3 无斜杠的 claim 不认（命令词表为准）", c is None, c)
    c, p = bb.parse_command("/deliver https://example.com/pull/7")
    ok("A4 /deliver 载荷切出", c == "/deliver" and p == "https://example.com/pull/7",
       (c, p))
    c, p = bb.parse_command("   /claim")
    ok("A5 前导空白容忍（行首态）", c == "/claim" and p == "", (c, p))
    c, p = bb.parse_command("/claim：我先占用")
    ok("A6 命令与载荷间无分隔符（`/claim：…`）不认——防近似词误触发",
       c is None and p == "", (c, p))


# ================================================================ [A] R3 标签与态

def group_label_state():
    print("[A] R3 · 入选标记与态（bounty 标签在 ∧ 态 ∈ {open, expired}）")
    st = mk_state(labels=["difficulty:medium"])          # 无 bounty 标签
    d = claim(st)
    ok("B1 无 `bounty` 标签 → 拒", d.ok is False and "bounty" in d.reason, d.reason)
    st = mk_state(state="settled", holder=None)          # 态判据单点（无持有者）
    d = claim(st, actor="bob")
    ok("B2 态为 settled（非 open/expired）→ 拒（不可认领）",
       d.ok is False and "不可认领" in d.reason, d.reason)
    st = mk_state(state="open")
    d = claim(st)
    ok("B3 态为 open → 通过并上锁", d.ok and d.to_state == "claimed"
       and d.holder == "alice", (d.ok, d.to_state, d.holder))
    st = mk_state(state="expired")
    d = claim(st)
    ok("B4 态为 expired → 通过（回板窗口可认领）", d.ok and d.to_state == "claimed",
       (d.ok, d.to_state))
    st = mk_state(labels=["bounty", "difficulty:medium"])   # 有入选标记、无态标签
    d = claim(st)
    ok("B5 有 `bounty` 无态标签 → 按 open 处置（试点口径，README 记载）",
       d.ok and d.from_state == "open", (d.ok, d.from_state))


# ================================================================ [B] R1 无持有者

def group_holder():
    print("[B] R1 · 无当前持有者（标记是权威记录：持有时标签可能仍为 open）")
    # 现场形态：态标签落后（仍 open）但标记里已有持有者 ⇒ 必须被持有者判据拦住。
    st = mk_state(state="open", holder="alice", due="2026-10-12T00:00:00Z")
    d = claim(st, actor="bob")
    ok("C1 已有持有者 → 拒（理由点名持有者与到期）", d.ok is False
       and "已有持有者 @alice" in d.reason, d.reason)
    st = mk_state(state="claimed", holder="alice", due="2026-10-12T00:00:00Z")
    d = claim(st, actor="bob")
    ok("C1b 态与标记一致（claimed）→ 同样拒（持有者判据先于态判据）",
       d.ok is False and "已有持有者 @alice" in d.reason, d.reason)
    st = mk_state(state="open", holder=None)
    d = claim(st, actor="bob")
    ok("C2 无持有者 → 通过", d.ok is True, d.reason)


# ================================================================ [C] R2 并发上限

def group_concurrency():
    print("[C] R2 · 并发认领上限（默认 2）")
    ok("D1 缺省上限 = 2（Config 缺省值即口径真源）", CFG.max_concurrent == 2,
       CFG.max_concurrent)
    st = mk_state(state="open")
    d = claim(st, actor="dave", active=1)
    ok("D2 已持有 1 个（未达上界）→ 通过", d.ok is True, d.reason)
    d = claim(st, actor="dave", active=2)
    ok("D3 已持有 2 个（达上界）→ 拒", d.ok is False and "上限 2" in d.reason,
       d.reason)
    cfg1 = bb.Config(max_concurrent=1)
    d = claim(st, actor="dave", active=1, cfg=cfg1)
    ok("D4 上限可配（=1 且已持有 1）→ 拒", d.ok is False and "上限 1" in d.reason,
       d.reason)


# ================================================================ [D] R4 仅认领人

def group_is_holder():
    print("[D] R4 · 仅认领人可交付 / 释放")
    st = mk_state(state="claimed", holder="alice",
                  due="2026-10-12T00:00:00Z")
    d = deliver(st, actor="bob")
    ok("E1 非持有者 /deliver → 拒", d.ok is False and "仅当前持有者" in d.reason,
       d.reason)
    d = bb.handle_command(st, "/withdraw", "", "/withdraw", "bob", NOW, CFG)
    ok("E2 非持有者 /withdraw → 拒", d.ok is False and "仅当前持有者" in d.reason,
       d.reason)
    d = deliver(st, actor="alice")
    ok("E3 持有者 /deliver → 通过（转 delivered，轮次 +1）",
       d.ok and d.to_state == "delivered" and d.rounds == 1,
       (d.ok, d.to_state, d.rounds))
    d = bb.handle_command(st, "/withdraw", "", "/withdraw", "alice", NOW, CFG)
    ok("E4 持有者 /withdraw → 通过（回板 open，清持有者与到期）",
       d.ok and d.to_state == "open" and d.holder is None and d.due_at is None,
       (d.ok, d.to_state, d.holder))


# ================================================================ [E] R5 交付件

def group_payload():
    print("[E] R5 · 交付必须带链接或证据块")
    st = mk_state(state="claimed", holder="alice")
    d = bb.handle_command(st, "/deliver", "", "/deliver", "alice", NOW, CFG)
    ok("F1 空载荷且无围栏 → 拒", d.ok is False and "必须带链接" in d.reason,
       d.reason)
    d = deliver(st, payload="见附件", body="/deliver 见附件")
    ok("F2 无链接无围栏的说明文字 → 拒", d.ok is False and "必须带链接" in d.reason,
       d.reason)
    d = deliver(st, payload="https://github.com/o/r/pull/7")
    ok("F3 https 链接 → 通过", d.ok is True, d.reason)
    d = deliver(st, payload="http://example.com/evidence")
    ok("F4 http 链接 → 通过", d.ok is True, d.reason)
    d = deliver(st, payload="复现读数如下",
                body="/deliver 复现读数如下\n```\n7 passed in 0.42s\n```")
    ok("F5 载荷无链接但正文带围栏证据块 → 通过", d.ok is True, d.reason)


# ================================================================ [F] 生命周期与账本

def group_lifecycle():
    print("[F] 生命周期与账本（验收 / 结算 / 轮次 / 超时回板 / 幂等 / 荣誉榜）")
    st = mk_state(state="delivered", holder="alice", rounds=1)
    d = verify(st, actor="bob", maint=False)
    ok("G1 非维护者 /verify → 拒", d.ok is False and "仅维护者" in d.reason, d.reason)
    st_open = mk_state(state="open")
    d = verify(st_open)
    ok("G2 态非 delivered 的 /verify → 拒", d.ok is False and "待验收面" in d.reason,
       d.reason)
    d = verify(st)
    ok("G3 维护者 /verify pass → 通过（转 verified）",
       d.ok and d.to_state == "verified", (d.ok, d.to_state))
    d = verify(st, payload="fail 读数不可复跑")
    ok("G4 /verify fail → 回 claimed 返工且**不扣分**（v1.0：发布者不能凭一次不满扣分）",
       d.ok and d.to_state == "claimed" and d.delta == 0,
       (d.ok, d.to_state, d.delta))
    st_v = mk_state(state="verified", holder="alice", rounds=1)
    d = settle(st_v, actor="bob", maint=False)
    ok("G5 非维护者 /settle → 拒", d.ok is False and "仅维护者" in d.reason, d.reason)
    d = settle(st_open)
    ok("G6 态非 verified 的 /settle → 拒",
       d.ok is False and "不可结算" in d.reason, d.reason)
    d = settle(st_v)
    ok("G7 维护者 /settle → 质量化按 medium 记 +6（rounds=1 ⇒ round=0 ⇒ 2×）",
       d.ok and d.to_state == "settled" and d.delta == 6
       and (d.event.get("formula") or {}).get("round") == 0,
       (d.ok, d.to_state, d.delta))
    st_r3 = mk_state(state="delivered", holder="alice", rounds=3)
    d = deliver(st_r3, actor="alice")
    ok("G8 轮次用尽后再交付 → 判**无效交付**（转 disputed、记 −base）",
       d.ok and d.to_state == "disputed"
       and d.delta == -bb.base_of(st_r3.difficulty),
       (d.ok, d.to_state, d.delta))
    st_due = mk_state(state="claimed", holder="carol",
                      due="2026-10-12T09:00:00Z")
    out = bb.sweep([st_due], bb.parse_ts("2026-10-12T09:00:00Z"), CFG)
    ok("G9 超期 claimed → 回板 open 且事件记 −2×base（负分归属原持有者）",
       len(out) == 1 and out[0].to_state == "open"
       and out[0].delta == -2 * bb.base_of(st_due.difficulty)
       and out[0].event.get("holder") == "carol"
       and out[0].holder is None,
       (len(out), out[0].to_state if out else None))
    out = bb.sweep([st_due], bb.parse_ts("2026-10-11T00:00:00Z"), CFG)
    ok("G10 未超期 → 不动（sweep 空表）", out == [], out)
    ev = {"ts": "2026-10-09T00:00:00Z", "issue": 1, "action": "settle",
          "actor": "m", "holder": "alice", "delta": 3}
    ev["id"] = bb.event_id(ev)
    led = bb.append_events([], [ev])
    led2 = bb.append_events(led, [dict(ev)])
    ok("G11 账本按 id 幂等（同事件重复投递只入一次）",
       len(led) == 1 and len(led2) == 1, (len(led), len(led2)))
    d_rej = claim(mk_state(state="claimed", holder="alice"), actor="bob")
    led3 = bb.append_events(led, [d_rej.event])
    ok("G12 append-only：拒绝也留痕（delta=0）且不改写既有行",
       len(led3) == 2 and led3[0] == led[0]
       and d_rej.event.get("action") == "reject" and d_rej.event.get("delta") == 0,
       (len(led3), d_rej.event.get("action")))
    board = bb.render_board(led3)
    ok("G13 荣誉榜确定性：同账本两次生成逐字节相同",
       board == bb.render_board(led3), "")
    ok("G14 荣誉榜含贡献者与声誉分（alice +3 ／ bob 0）",
       "@alice | 3" in board and "@bob | 0" in board, board[:200].replace("\n", " | "))
    ok("G15 被拒命令记在**尝试者**头上（bob 计 1 次被拒，不计入持有者 alice）",
       "@bob | 0 | 0 | 0 | 0 | 0 | 1" in board, board.replace("\n", " | ")[:400])
    # ---- 质量化计分（v1.0；依据《质量化计分标准与方式 v1.0》）----
    # 注：本承载面 max_rounds=3 ⇒ rounds ≤ 3 ⇒ raw ≥ 2/3 ⇒ max(1,·) 永不生效；
    # 故 G17 直接测函数（rounds=5），否则保底规则在承载面上不可观测。
    _q = []
    for _diff, _base in (("difficulty:expert", 10), ("difficulty:hard", 6),
                         ("difficulty:medium", 3), ("difficulty:easy", 1)):
        _q.append((bb.quality_delta(_base, 1)[0], bb.quality_delta(_base, 2)[0],
                   bb.quality_delta(_base, 3)[0], _base))
    ok("G16 质量化三档：首交付 2×base ／ 中性 1×base ／ 返工 2/3×base（四档难度）",
       all(a1 == 2 * b1 and a2 == b1 and a3 == max(1, bb._round_half_up(b1 * 2.0 / 3))
           for a1, a2, a3, b1 in _q), _q)
    ok("G17 保底 max(1,·)：低 base × 高轮次时生效（quality_delta(1,5) == 1）",
       bb.quality_delta(1, 5)[0] == 1, bb.quality_delta(1, 5)[0])
    ok("G18 舍入 half-up：2.5→3 ／ 4.5→5（且与内置 round 分歧：2／4）",
       bb._round_half_up(2.5) == 3 and bb._round_half_up(4.5) == 5
       and round(2.5) == 2 and round(4.5) == 4,
       (bb._round_half_up(2.5), bb._round_half_up(4.5)))
    _stq = mk_state(state="verified", holder="alice", rounds=3,
                    difficulty="difficulty:hard")
    _dq = settle(_stq)
    _fq = _dq.event.get("formula") or {}
    ok("G19 结算事件带 formula 快照（base/rounds/round/den/delta 齐备）",
       _dq.ok and {"base", "rounds", "round", "den", "delta"} <= set(_fq)
       and _fq.get("base") == 6 and _fq.get("round") == 2 and _dq.delta == 4,
       (_dq.delta, _fq))
    _ok1, _bad1 = bb.rescore([_dq.event])
    ok("G20 rescore 全等：按 formula 复算 == 落盘 delta", _ok1 and not _bad1, _bad1)
    _tam = dict(_dq.event)
    _tam["delta"] = int(_tam["delta"]) + 1
    _ok2, _bad2 = bb.rescore([_tam])
    ok("G21 rescore 抓篡改：改 delta 必被点名（含事件 id）",
       (not _ok2) and bool(_bad2) and _bad2[0][0] == _dq.event.get("id"), _bad2)
    # ---- E（验收条目通过率）：/verify partial p/t ⇒ 分母进标记快照并随态迁移继承 ----
    _d22 = verify(mk_state(state="delivered", holder="alice", rounds=2,
                          difficulty="difficulty:hard"), payload="partial 3/5 条目 c1/c2/c4 过")
    ok("G22 /verify partial 3/5 → 转 verified 且标记带验收条目快照 [3,5]",
       _d22.ok and _d22.to_state == "verified" and '"criteria":[3,5]' in _d22.comment,
       _d22.comment[-160:])
    _st23 = bb.IssueState(number=101, labels=("bounty", "bounty:verified", "difficulty:hard"),
                          has_bounty=True, state="verified", holder="alice", rounds=2, seq=1,
                          difficulty="difficulty:hard", author="FuRongJun-1999", criteria=(3, 5))
    _d23 = settle(_st23)
    ok("G23 E 进结算：hard base=6 × 2×(3/5) ÷ 2 = 3.6 → half_up 4",
       _d23.ok and _d23.delta == 4
       and (_d23.event.get("formula") or {}).get("e_total") == 5,
       (_d23.delta, _d23.event.get("formula")))
    _ok24, _bad24 = bb.rescore([_d23.event])
    ok("G24 rescore 按 e_pass/e_total 复算一致", _ok24 and not _bad24, _bad24)
    _st25 = mk_state(state="delivered", holder="alice")
    _d25a = verify(_st25, payload="partial 5/3 越界")
    _d25b = verify(_st25, payload="partial abc 非数")
    ok("G25 partial 数值非法/不可解析 → 拒（criteria_malformed）",
       _d25a.ok is False and "非法" in _d25a.reason
       and _d25b.ok is False and "partial 须给" in _d25b.reason,
       (_d25a.reason, _d25b.reason))
    _st26 = bb.IssueState(number=101, labels=("bounty", "bounty:verified", "difficulty:medium"),
                          has_bounty=True, state="verified", holder="alice", rounds=1, seq=2,
                          difficulty="difficulty:medium", author="FuRongJun-1999", criteria=(1, 2))
    _d26 = settle(_st26)
    ok("G26 E 快照参与结算：medium base=3 × 2×(1/2) ÷ 1 = 3",
       _d26.ok and _d26.delta == 3
       and (_d26.event.get("formula") or {}).get("e_pass") == 1,
       (_d26.delta, _d26.event.get("formula")))
    _d27 = verify(mk_state(state="delivered", holder="alice"), payload="pass 全过")
    ok("G27 /verify pass → 清空 E 快照（E≡1）",
       _d27.ok and "criteria" not in _d27.comment, _d27.comment[-160:])
    # ---- 招标模式（参考招投标法：投标 → 截止 → 定标 → 落标）----
    _mkb = lambda **kw: bb.IssueState(number=101,
        labels=("bounty", "bounty:" + kw.get("state", "contest"), kw.get("diff", "difficulty:hard")),
        has_bounty=True, state=kw.get("state", "contest"), holder=kw.get("holder"),
        due_at=kw.get("due"), rounds=kw.get("rounds", 0), seq=1,
        difficulty=kw.get("diff", "difficulty:hard"), author="FuRongJun-1999",
        bidders=kw.get("bidders", ()))
    def _bd(st, cmd, payload, actor="alice", maint=False):
        return bb.handle_command(st, cmd, payload, f"{cmd} {payload}", actor, NOW, CFG,
                                 is_maintainer=maint)
    _d28 = _bd(_mkb(), "/bid", "https://example.com/pull/1")
    ok("G28 /bid 投标 → 态保持 contest 且标记带投标人 [alice]",
       _d28.ok and _d28.to_state == "contest" and '"bidders":["alice"]' in _d28.comment,
       _d28.comment[-150:])
    _d29 = _bd(_mkb(bidders=("alice",)), "/bid", "https://example.com/pull/2")
    ok("G29 一人一投：同一人二次投标 → 拒（duplicate_bid）",
       _d29.ok is False and "一人一投" in _d29.reason, _d29.reason)
    _d30 = _bd(_mkb(due="2020-01-01T00:00:00Z"), "/bid", "https://example.com/pull/3")
    ok("G30 投标截止后 → 拒（bid_deadline_passed）",
       _d30.ok is False and "截止时间已过" in _d30.reason, _d30.reason)
    _d31 = _bd(_mkb(state="open"), "/bid", "https://example.com/pull/4")
    ok("G31 非招标态 /bid → 拒（state_not_bidding）",
       _d31.ok is False and "不接受投标" in _d31.reason, _d31.reason)
    _d32 = _bd(_mkb(bidders=("alice", "bob", "carol")), "/select", "bob 读数最全",
                actor="FuRongJun-1999", maint=True)
    ok("G32 /select 定标 → 转 delivered、holder=中标者、rounds=1（首交付）",
       _d32.ok and _d32.to_state == "delivered" and _d32.holder == "bob"
       and _d32.rounds == 1, (_d32.to_state, _d32.holder, _d32.rounds))
    ok("G33 落标者各一条落选事件：hard → 2 分（v0.4 表 0/1/2/4）",
       len(_d32.extra_events) == 2
       and {e["actor"] for e in _d32.extra_events} == {"alice", "carol"}
       and all(e["delta"] == 2 for e in _d32.extra_events),
       [(e["actor"], e["delta"]) for e in _d32.extra_events])
    _d34 = _bd(_mkb(bidders=("alice", "bob"), diff="difficulty:easy"), "/select", "bob",
                actor="FuRongJun-1999", maint=True)
    ok("G34 0 分落选也写事件（easy → delta=0；否则与「未投标」同形）",
       len(_d34.extra_events) == 1 and _d34.extra_events[0]["delta"] == 0,
       [(e["actor"], e["delta"]) for e in _d34.extra_events])
    _d35a = _bd(_mkb(bidders=("alice",)), "/select", "alice", actor="bob")
    _d35b = _bd(_mkb(bidders=("alice",)), "/select", "dave", maint=True)
    _d35c = _bd(_mkb(), "/select", "alice", maint=True)
    ok("G35 定标越权/非投标人/无投标 → 三种皆拒",
       _d35a.ok is False and "仅维护者" in _d35a.reason
       and _d35b.ok is False and "须为已投标者之一" in _d35b.reason
       and _d35c.ok is False and "尚无投标" in _d35c.reason,
       (_d35a.reason[:20], _d35b.reason[:20], _d35c.reason[:20]))
    _ok36, _bad36 = bb.rescore(list(_d32.extra_events) + list(_d34.extra_events))
    ok("G36 落选分 rescore 一致（按难度表复算）", _ok36 and not _bad36, _bad36)
    # ---- 价值评价（影响等级；可配置表 + 判定留痕 + 不参与计分）----
    _stap = bb.IssueState(number=101, labels=("bounty", "bounty:delivered", "difficulty:hard"),
                          has_bounty=True, state="delivered", holder="alice", rounds=1, seq=1,
                          difficulty="difficulty:hard", author="FuRongJun-1999")
    def _ap(payload, actor="FuRongJun-1999", maint=True, s=None):
        return bb.handle_command(s or _stap, "/appraise", payload, "/appraise " + payload,
                                 actor, NOW, CFG, is_maintainer=maint)
    _d37 = _ap("A 检索核心链路，影响面大")
    ok("G37 /appraise：态不变、标记与事件均带 impact、**delta 恒 0**（不参与计分）",
       _d37.ok and _d37.to_state == "delivered" and '"impact":"A"' in _d37.comment
       and _d37.event.get("impact") == "A" and _d37.delta == 0,
       (_d37.to_state, _d37.delta, _d37.event.get("impact")))
    _d38 = _ap("Z 随便")
    ok("G38 未知等级 → 拒，且提示当前表（表可调）",
       _d38.ok is False and "当前表" in _d38.reason, _d38.reason)
    _d39 = _ap("S")
    ok("G39 价值评价无依据 → 拒（否则不可追溯）",
       _d39.ok is False and "必须带依据" in _d39.reason, _d39.reason)
    _d40 = _ap("A 有依据", actor="bob", maint=False)
    ok("G40 非维护者 /appraise → 拒（人审闸）",
       _d40.ok is False and "仅维护者" in _d40.reason, _d40.reason)
    _old_g, _old_c = bb.IMPACT_GRADES, bb.IMPACT_CRITERIA
    try:
        bb.IMPACT_GRADES = ("甲", "乙", "丙", "丁")
        bb.IMPACT_CRITERIA = {"甲": "最高", "乙": "高", "丙": "中", "丁": "低"}
        _ok41a = _ap("甲 换表后生效").ok
        _ok41b = not _ap("S 旧等级").ok
    finally:
        bb.IMPACT_GRADES, bb.IMPACT_CRITERIA = _old_g, _old_c
    ok("G41 **等级表可调**：换成甲乙丙丁后新等级生效、旧等级被拒、还原即恢复",
       _ok41a and _ok41b and _ap("S 还原").ok, (_ok41a, _ok41b))
    _d42 = verify(bb.IssueState(number=101, labels=("bounty", "bounty:delivered", "difficulty:hard"),
                                has_bounty=True, state="delivered", holder="alice", rounds=1,
                                seq=2, difficulty="difficulty:hard", author="FuRongJun-1999",
                                impact="A"), payload="pass 全过")
    ok("G42 impact 随状态迁移继承（verify 后的新标记仍带等级）",
       _d42.ok and '"impact":"A"' in _d42.comment, _d42.comment[-140:])


# ================================================================ [G] 离线两模式自证

# 生效条件：argv 为命令行参数列表时以子进程真跑实现脚本（cwd=仓根、UTF-8、超时 300s），
# 返回 CompletedProcess（供断言 rc/stdout/落盘件）。
def run_impl(*argv):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-X", "utf8", IMPL, *argv],
                          cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=300)


def group_offline(tmp):
    print("[G] 离线两模式自证（--dry-run ／ --state 真跑子进程）")
    r = run_impl("--dry-run")
    out = r.stdout or ""
    ok("H1 --dry-run 退出码 0（离线演练可一键跑）", r.returncode == 0,
       (r.returncode, (r.stderr or "")[-200:]))
    need = ("open → claimed", "claimed → delivered", "delivered → verified",
            "verified → settled", "claimed → open", "expired")
    ok("H2 演练日志覆盖全部态迁移（claim→deliver→verify→settle ＋ 超时回板）",
       all(x in out for x in need), [x for x in need if x not in out])
    ok("H3 演练日志含账本段与荣誉榜段",
       "---- 账本（" in out and "---- 荣誉榜（由账本机械生成）----" in out, "")
    ok("H4 演练为纯离线（不触网）：日志无 http 请求痕迹",
       "GitHub API" not in out and "网络错误" not in out, "")

    store = os.path.join(tmp, "mirror.json")
    r1 = run_impl("--state", store, "--open-issue", "201", "--labels",
                  "bounty,difficulty:medium", "--author", "FuRongJun-1999")
    r2 = run_impl("--state", store, "--command", "/claim", "--as", "zoe",
                  "--at", "2026-10-09T01:00:00Z")
    r3 = run_impl("--state", store, "--sweep", "--at", "2026-10-12T01:00:00Z")
    r4 = run_impl("--state", store)
    with io.open(store, encoding="utf-8") as fh:
        doc = json.load(fh)
    rec = doc["issues"]["201"]
    ok("H5 --state 三腿全通（建题 / 认领 / 超时回板）",
       r1.returncode == 0 and r2.returncode == 0 and r3.returncode == 0,
       (r1.returncode, r2.returncode, r3.returncode))
    ok("H6 镜像落盘正确：标签回 bounty:open、历史含 claim→expire、账本 2 条",
       "bounty:open" in rec["labels"]
       and [h["action"] for h in rec["history"]] == ["/claim", "/expire"]
       and len(doc["ledger"]) == 2,
       (rec["labels"], [h["action"] for h in rec["history"]], len(doc["ledger"])))
    ok("H7 镜像看板可读（--state 无动作时打印各题一行）",
       r4.returncode == 0 and "#201" in (r4.stdout or ""), (r4.stdout or "")[:120])

    jsonl = os.path.join(tmp, "events.jsonl")
    with io.open(jsonl, "w", encoding="utf-8", newline="\n") as fh:
        for e in doc["ledger"]:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    ledger = os.path.join(tmp, "ledger.json")
    board = os.path.join(tmp, "board.md")
    r5 = run_impl("--ledger-append", jsonl, "--ledger", ledger)
    r6 = run_impl("--board-out", board, "--ledger", ledger)
    with io.open(ledger, encoding="utf-8") as fh:
        ldoc = json.load(fh)
    with io.open(board, encoding="utf-8") as fh:
        btext = fh.read()
    ok("H8 账本收口：--ledger-append 生成带 _schema 的账本（2 条事件）",
       r5.returncode == 0 and ldoc.get("_schema") and len(ldoc["events"]) == 2,
       (r5.returncode, len(ldoc.get("events") or [])))
    r7 = run_impl("--ledger-append", jsonl, "--ledger", ledger)
    with io.open(ledger, encoding="utf-8") as fh:
        ldoc2 = json.load(fh)
    ok("H9 账本收口幂等：重复并入同批 JSONL 不增行",
       r7.returncode == 0 and len(ldoc2["events"]) == 2, len(ldoc2["events"]))
    ok("H10 荣誉榜由账本生成（含贡献者行）",
       r6.returncode == 0 and "荣誉榜" in btext and "@zoe" in btext,
       btext[:200].replace("\n", " | "))


# ================================================================ [H] 真模式路由（假客户端，不触网）

class _FakeClient:
    """假 GitHub 客户端：只实现**路由层用到的读面**，把写动作记进 `writes`。

    为什么要有：真模式的写路径原则上只能在 GitHub 上跑，但「路由判据」（PR 评论不处理／
    自带标记不处理／非命令不处理／缺 --apply 不写远端／交付链接读 PR 元数据）**是纯路由
    逻辑**，可用假客户端在本地断言清楚——否则 workflow 那半边的判据只能靠人工看。
    """

    def __init__(self, repo="o/r", comments=(), pr=None, active=0,
                 labels_ready=False):
        self.repo = repo
        self._comments = list(comments)
        self._pr = pr
        self._active = active
        self.labels_ready = labels_ready
        self.writes = []

    def comments(self, n):
        return list(self._comments)

    def pull(self, n):
        return self._pr

    def count_active_claims(self, actor, exclude=None, limit=10):
        return self._active

    def ensure_labels(self, specs):
        self.labels_ready = True
        return []

    def set_labels(self, n, add, remove):
        self.writes.append(("labels", n, tuple(add), tuple(remove)))

    def comment(self, n, body):
        self.writes.append(("comment", n, body))


# 生效条件：payload 为事件体字典、client 为 _FakeClient 时返回 handle_issue_comment 的
# (退出码, 事件列表)，打印面静默（out 给空函数）。
def _route(payload, client, apply=False):
    return bb.handle_issue_comment(payload, bb.Config(), client, apply=apply,
                                   out=lambda *_a: None)


def _issue_payload(body, labels=("bounty", "bounty:open", "difficulty:medium"),
                   number=301, actor="zoe", assoc="NONE", is_pr=False):
    issue = {"number": number, "labels": [{"name": x} for x in labels],
             "user": {"login": "FuRongJun-1999"}}
    if is_pr:
        issue["pull_request"] = {"url": "https://api.github.com/repos/o/r/pulls/9"}
    return {"issue": issue,
            "comment": {"body": body, "user": {"login": actor},
                        "author_association": assoc}}


def group_routing():
    print("[H] 真模式路由（假客户端：PR 评论／自带标记／非命令／计划不写／PR 元数据）")
    code, evs = _route(_issue_payload("/claim", is_pr=True), _FakeClient())
    ok("I1 PR 评论 → 无动作（不写、不产事件）", code == 0 and evs == [], (code, evs))
    marked = "**[悬赏板] 认领成功**\n<!-- bounty:v1 {\"state\":\"claimed\"} -->"
    code, evs = _route(_issue_payload(marked), _FakeClient())
    ok("I2 悬赏板自身留言（含标记）→ 无动作（防自触发循环）",
       code == 0 and evs == [], (code, evs))
    code, evs = _route(_issue_payload("我先看看这个任务，稍后 /claim"), _FakeClient())
    ok("I3 非命令评论 → 无动作", code == 0 and evs == [], (code, evs))
    cli = _FakeClient()
    code, evs = _route(_issue_payload("/claim"), cli, apply=False)
    ok("I4 计划模式（缺 --apply）→ 不写任何远端状态",
       code == 0 and cli.writes == [] and len(evs) == 1, (cli.writes, len(evs)))
    cli = _FakeClient()
    code, evs = _route(_issue_payload("/claim"), cli, apply=True)
    ok("I5 应用模式 → 加标签之一 ＋ 发一条评论（且标签体系就绪）",
       code == 0 and cli.labels_ready is True and len(cli.writes) == 2
       and cli.writes[0][0] == "labels" and cli.writes[1][0] == "comment",
       cli.writes)
    pr = {"title": "fix: 读数可复跑", "state": "open",
          "head": {"sha": "abcdef1234567890"}}
    cli = _FakeClient(comments=["<!-- bounty:v1 {\"state\":\"claimed\","
                                "\"holder\":\"zoe\",\"rounds\":0,\"seq\":1,"
                                "\"due_at\":\"2026-10-12T01:00:00Z\"} -->"], pr=pr)
    url = "https://github.com/o/r/pull/77"
    code, evs = _route(_issue_payload(f"/deliver {url}", actor="zoe"), cli,
                       apply=True)
    ok("I6 交付链接指向本仓 PR → 事件带 PR 元数据（pull-requests: read 那条腿）",
       code == 0 and evs and (evs[0].get("pr") or {}).get("number") == 77
       and (evs[0].get("pr") or {}).get("head_sha") == "abcdef123456",
       evs[0].get("pr") if evs else None)


_GROUPS = (group_parse, group_label_state, group_holder, group_concurrency,
           group_is_holder, group_payload, group_lifecycle, group_routing)


# 生效条件：无必需形参时清账并跑 [0]–[F] 全组（离线子进程组由调用方另跑），返回失败项前缀集合。
def run_suite():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    for fn in _GROUPS:
        fn()
    return {n.split(" ", 1)[0] for n in FAILS}


# ================================================================ 定点变异（注入判据失效 ⇒ 必红）
# 每条变异 = 把**一条校验**短路（源码级、只改内存里 exec 的副本，不落盘），
# 期望转红的断言项**恰好**等于声明集合：多红 = 断言语义纠缠，少红 = 该判据空转。

_MUTATIONS = (
    ("M0 关命令识别（任意首词当命令）",
     "        if word in COMMANDS:",
     "        if True:  # MUT", {"A2", "A3", "A6", "I3"}),
    ("M1 关 R3 标签判据（无 bounty 标签也放行）",
     "    if not st.has_bounty:",
     "    if False:  # MUT", {"B1"}),
    ("M2 关 R3 态判据（非 open/expired 也放行）",
     "    if st.state not in CLAIMABLE_STATES:",
     "    if False:  # MUT", {"B2"}),
    ("M3 关 R1 无持有者判据（撞锁放行）",
     "    if st.holder:",
     "    if False:  # MUT", {"C1", "C1b"}),
    ("M4 关 R2 并发上限判据（无限并发）",
     "    if active >= cap:",
     "    if False:  # MUT", {"D3", "D4"}),
    ("M5 关 R4 仅认领人判据（他人可交付/释放）",
     "    if st.holder != actor:",
     "    if False:  # MUT", {"E1", "E2"}),
    ("M6 关 R5 链接判据（无据交付放行）",
     "    if _URL_RE.search(payload or \"\"):",
     "    if True:  # MUT", {"F1", "F2"}),
    ("M7 关 R5 证据块判据（围栏交付不再被认）",
     "    if _FENCE_RE.search(body or \"\"):",
     "    if False:  # MUT", {"F5"}),
    ("M8 关质量乘数（完成分恒 base）",
     "    raw = base * 2.0 * _e / (r + 1)",
     "    raw = float(base)  # MUT", {"G7", "G16", "G19", "G20", "G23", "G24"}),
    ("M9 去保底 max(1,·)",
     "    d = max(1, _round_half_up(raw))",
     "    d = _round_half_up(raw)  # MUT", {"G17"}),
    ("M10 /verify fail 又扣分（退回返工不放过）",
     "                       delta=0, criteria=())",
     "                       delta=-5)  # MUT", {"G4"}),
    ("M11 轮次用尽不判无效（不记 −base）",
     "        _d, _f = invalid_delta(base_of(st.difficulty))",
     "        _d, _f = 0, None  # MUT", {"G8"}),
    ("M12 超时不按 base 缩放（回到固定 −1）",
     "        _td, _tf = timeout_delta(base_of(st.difficulty))",
     "        _td, _tf = -1, None  # MUT", {"G9"}),
    ("M13 去 formula 快照（复算链断）",
     "    if formula is not None:",
     "    if False:  # MUT", {"G7", "G19", "G20", "G23", "G24", "G26"}),
    ("M14 舍入改内置 round（银行家）",
     "    return int(math.floor(x + 0.5))",
     "    return int(round(x))  # MUT", {"G18"}),
    ("M15 关 E 乘数（E ≡ 1）",
     "    raw = base * 2.0 * _e / (r + 1)",
     "    raw = base * 2.0 / (r + 1)  # MUT", {"G23", "G24", "G26"}),
    ("M16 不写验收条目快照（E 不可复算）",
     "    if len(_cr) == 2:",
     "    if False:  # MUT", {"G22"}),
    ("M17 partial 不校验数值范围（越界放行）",
     "        if _t <= 0 or _p < 0 or _p > _t:",
     "        if False:  # MUT", {"G25"}),
    ("M18 rescore 忽略 E（复算链与结算口径分叉）",
     "            _e = (int(f.get(\"e_pass\") or 0) / int(f[\"e_total\"])) if f.get(\"e_total\") else 1.0",
     "            _e = 1.0  # MUT", {"G24"}),
    ("M19 关一人一投判据（可重复投标刷名单）",
     "    if actor in st.bidders:",
     "    if False:  # MUT", {"G29"}),
    ("M20 关投标截止判据（截止后可改标）",
     "            if now >= parse_ts(st.due_at):",
     "            if False:  # MUT", {"G30"}),
    ("M21 关招标态判据（非招标也收标）",
     "    if st.state != \"contest\":",
     "    if False:  # MUT", {"G31"}),
    ("M22 落选分恒 0（难度表失效）",
     "    d = LOSER_SCORES.get(difficulty or \"\", 0)",
     "    d = 0  # MUT", {"G33", "G36"}),
    ("M23 不写 0 分落选事件（与未投标同形）",
     "        extra.append(_ev)",
     "        if _ld: extra.append(_ev)  # MUT", {"G34"}),
    ("M24 定标不校验中标人（任选一人）",
     "    if winner not in st.bidders:",
     "    if False:  # MUT", {"G35"}),
    ("M25 rescore 落选分恒 0",
     "            d = LOSER_SCORES.get(\"difficulty:\" + str(f.get(\"difficulty\") or \"\"), 0)",
     "            d = 0  # MUT", {"G36"}),
    ("M26 关影响等级表校验（任意等级放行）",
     "    if grade not in IMPACT_GRADES:",
     "    if False:  # MUT", {"G38", "G41"}),
    ("M27 关「评价必须带依据」（不可追溯）",
     "    if not reason:",
     "    if False:  # MUT", {"G39"}),
    ("M28 不写影响等级快照（跨态丢失）",
     "    if _im:" + chr(10) + '        marker["impact"] = _im',
     "    if False:  # MUT" + chr(10) + '        marker["impact"] = _im', {"G37", "G42"}),
    ("M29 关价值评价的维护者闸（越权可评）",
     "    if not is_maintainer:",
     "    if False:  # MUT", {"G40"}),
)


# 生效条件：fn_name 为模块内函数名、old 为唯一锚点、new 为替换文本时，用
# inspect.getsource 取该函数源码，就地 exec 到模块全局（运行中的实现被替换），
# 返回复原函数；锚点命中次数 ≠1 抛 AnchorMiss（调用方记 ANCHOR-MISS）。
class AnchorMiss(Exception):
    pass


def _mut_source(fn_name, old, new):
    orig = getattr(bb, fn_name)
    src = inspect.getsource(orig)
    if src.count(old) != 1:
        raise AnchorMiss(f"{fn_name}: 锚点命中 {src.count(old)} 次（期望 1）：{old!r}")
    exec(compile(src.replace(old, new), f"<bounty-{fn_name}-mut>", "exec"),
         vars(bb))

    def _restore():
        setattr(bb, fn_name, orig)
    return _restore


#: 变异 → 目标函数（锚点落在哪个函数里就变异哪个）。
_MUT_TARGETS = (("M0", "parse_command"), ("M1", "_check_claimable"),
                ("M2", "_check_claimable"), ("M3", "_check_no_holder"),
                ("M4", "_check_concurrency"), ("M5", "_check_is_holder"),
                ("M6", "_check_payload"), ("M7", "_check_payload"),
                ("M8", "quality_delta"), ("M9", "quality_delta"),
                ("M10", "_do_verify"), ("M11", "_do_deliver"),
                ("M12", "sweep"), ("M13", "_accept"),
                ("M14", "_round_half_up"), ("M15", "quality_delta"),
                ("M16", "_accept"), ("M17", "_do_verify"),
                ("M18", "rescore"), ("M19", "_do_bid"), ("M20", "_do_bid"),
                ("M21", "_do_bid"), ("M22", "loser_delta"),
                ("M23", "_do_select"), ("M24", "_do_select"),
                ("M25", "rescore"), ("M26", "_do_appraise"), ("M27", "_do_appraise"),
                ("M28", "_accept"), ("M29", "_do_appraise"))


def _anchor_preflight():
    """锚点自检：任一锚点在当前实现里命中次数 ≠1 → ANCHOR-MISS（退出码 2）。"""
    bad = []
    for (name, _old, _new, _exp), (_mid, fn) in zip(_MUTATIONS, _MUT_TARGETS):
        src = inspect.getsource(getattr(bb, fn))
        if src.count(_old) != 1:
            bad.append((name, src.count(_old)))
    if not bad:
        return 0
    for name, n in bad:
        print(f"  ANCHOR-MISS {name}：锚点命中 {n} 次（期望 1）")
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _mutate_mode():
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：逐条短路一条校验，对应断言必须**恰好**转红\n")
    base_red = run_suite()
    print(f"\n  未变异基线：红项 {len(base_red)} "
          f"{'（应为 0）' if not base_red else sorted(base_red)}")
    bad = []
    if base_red:
        bad.append(f"基线即转红：{sorted(base_red)}")
    for (name, old, new, expect), (_mid, fn) in zip(_MUTATIONS, _MUT_TARGETS):
        restore = _mut_source(fn, old, new)
        try:
            red = run_suite()
        except Exception as exc:                                  # noqa: BLE001
            red = {f"<变异体异常:{type(exc).__name__}>"}
        finally:
            restore()
        hit = red == set(expect)
        if not hit:
            bad.append(f"{name}：红项 {sorted(red)} ≠ 期望 {sorted(expect)}")
        print(f"  {'[PASS]' if hit else '[FAIL]'} {name}：红项 {len(red)}"
              f"（期望 {len(expect)}）"
              + ("" if hit else f" 实={sorted(red)} 期={sorted(expect)}"))
    print("\n定点变异：" + ("PASS（逐条恰好命中期望红项）" if not bad
                            else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--list" in argv:
        for name, _old, _new, exp in _MUTATIONS:
            print(f"  {name:<44} expect_red={len(exp)} {sorted(exp)}")
        return 0
    if "--mutate" in argv:
        return _mutate_mode()

    print("悬赏板状态机守卫（scripts/bounty_board.py · 纯逻辑层断言）")
    print("=" * 74)
    for fn in _GROUPS:
        fn()
    tmp = tempfile.mkdtemp(prefix="bounty_guard_")
    try:
        group_offline(tmp)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("=" * 74)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
        return 1
    print("ALL OK（反面证明见 --mutate）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
