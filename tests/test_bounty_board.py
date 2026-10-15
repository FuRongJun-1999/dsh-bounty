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
    ok("G32 /select 定标 → 转 delivered、holder=中标者、rounds=0（待首轮交付；中标者 /deliver 后为 1）",
       _d32.ok and _d32.to_state == "delivered" and _d32.holder == "bob"
       and _d32.rounds == 0, (_d32.to_state, _d32.holder, _d32.rounds))
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
    _d35b = _bd(_mkb(bidders=("alice",)), "/select", "dave", actor="carol",
                maint=True)
    _d35c = _bd(_mkb(), "/select", "alice", maint=True)
    _d35d = _bd(_mkb(bidders=("alice",), holder="bob"), "/select", "alice",
                actor="bob", maint=True)
    ok("G35 定标越权/非投标人/无投标/自持挑选 → 四种皆拒",
       _d35a.ok is False and "仅维护者" in _d35a.reason
       and _d35b.ok is False and "须为已投标者之一" in _d35b.reason
       and _d35c.ok is False and "尚无投标" in _d35c.reason
       # 自持（actor == holder）时即便是维护者也回避——回避优先于授权（对齐 R10）
       and _d35d.ok is False and "持有者" in _d35d.reason,
       (_d35a.reason[:20], _d35b.reason[:20], _d35c.reason[:20], _d35d.reason[:20]))
    _ok36, _bad36 = bb.rescore(list(_d32.extra_events) + list(_d34.extra_events))
    ok("G36 落选分 rescore 一致（按难度表复算）", _ok36 and not _bad36, _bad36)

    # ---- G46..：rescore 对**畸形 formula / delta** 的报告面（不得崩）----
    # `rescore` 是 `docs/bounty/README.md:144` 写明的**公开可复算入口**，职责是
    # 「逐条按事件自带 formula 重算并断言与 delta 一致」⇒ 畸形输入应落**结构化 bad**，
    # 而不是抛裸 ValueError 回溯（本仓输入级错误走 `BoardError` ⇒ 调用方退 2 的契约）。
    _SR = bb.SCORE_RULE

    def _rs1(formula, delta=10):
        try:
            return bb.rescore([{"id": "evt_m", "delta": delta, "formula": formula}])
        except Exception as _exc:                                   # noqa: BLE001
            return ("CRASH", type(_exc).__name__)

    _m = {}
    for _tag, _f in (
            ("e_total 非数值", {"rule": _SR, "kind": "complete", "base": 6, "round": 0,
                                "e_pass": 1, "e_total": "abc"}),
            ("round 非数值", {"rule": _SR, "kind": "complete", "base": 6, "round": "x",
                              "e_pass": 1, "e_total": 3}),
            ("e_pass 非数值", {"rule": _SR, "kind": "complete", "base": 6, "round": 0,
                               "e_pass": "x", "e_total": 3}),
            ("timeout base 非数值", {"rule": _SR, "kind": "timeout", "base": "x"}),
            ("invalid base 非数值", {"rule": _SR, "kind": "invalid", "base": "x"})):
        _r = _rs1(_f)
        _m[_tag] = _r
    ok("G46 畸形 formula 一律**不崩**、返回 (ok=False, bad)",
       all(isinstance(v, tuple) and v[0] is False and v[1]
           for v in _m.values()),
       {k: (v[0], (v[1][0][1][:26] if isinstance(v[1], list) and v[1] else v[1]))
        for k, v in _m.items()})
    ok("G47 畸形理由以 `malformed formula` 开头（与 missing/unknown 同款结构）",
       all(isinstance(v[1], list) and v[1] and v[1][0][1].startswith("malformed formula")
           for v in _m.values()),
       {k: (v[1][0][1][:30] if isinstance(v[1], list) and v[1] else v[1])
        for k, v in _m.items()})
    ok("G48 `bad` 三元组形状与既有条目一致（id, reason, delta, recomputed）",
       all(len(v[1][0]) == 4 and v[1][0][0] == "evt_m" and v[1][0][3] is None
           for v in _m.values()), '')

    _rd = [_rs1({"rule": _SR, "kind": "complete", "base": 6, "round": 0}, delta=d)
           for d in ("abc", None, [], {})]
    ok("G49 非数值 delta 不崩，落 `delta mismatch`",
       all(isinstance(v, tuple) and v[0] is False and v[1][0][1] == "delta mismatch"
           for v in _rd), _rd)
    ok("G50 数值字符串 delta 仍按数值处理（不误判）",
       _rs1({"rule": _SR, "kind": "complete", "base": 10, "round": 0}, delta="20")[0] is True,
       _rs1({"rule": _SR, "kind": "complete", "base": 10, "round": 0}, delta="20"))

    # G51 用**防御式**调用（M44 会把 `_as_int` 改成直接抛）——否则变异体会让整套崩，
    # 变异框架只能记 `<变异体异常>`，无法定向点名 G51。
    _ai_vals = ("abc", None, [], "12", 7.9)
    _ai_ok = True
    _ai_res = []
    for _x in _ai_vals:
        try:
            _ai_res.append(bb._as_int(_x))
        except Exception:                                            # noqa: BLE001
            _ai_ok = False
            _ai_res.append(None)
    _ai_res = tuple(_ai_res)
    ok("G51 `_as_int` 宽容且不抛（非法 ⇒ 默认值；合法照转）",
       _ai_ok and _ai_vals == ("abc", None, [], "12", 7.9)
       and _ai_res == (0, 0, 0, 12, 7),
       f"{_ai_vals} → {_ai_res}")

    # G52 不另立：合法事件的 `rescore` 一致性已由 **G20** 覆盖（同一断言重复会让
    # M8/M13 的红项集合多出一项，从而破坏「恰好命中」的变异自证契约）。

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

    # ---- ★本笔新增（缺陷 #269A/B/C）：自评/自审隔离与自定标禁令 ----
    _L271 = ("bounty", "bounty:open", "difficulty:hard")
    _st271 = bb.IssueState(number=271, labels=_L271, has_bounty=True, state="open",
                           holder=None, rounds=0, seq=1, difficulty="difficulty:hard",
                           author="FuRongJun-1999")
    _apA = bb.handle_command(_st271, "/appraise", "S 先插一条自评", "/appraise S 先插一条自评",
                             "rev1", NOW, CFG, is_maintainer=True)
    _cl = bb.handle_command(
        bb.build_state(271, list(_L271), [_apA.comment], author="FuRongJun-1999"),
        "/claim", "", "/claim", "rev1", NOW, CFG)
    ok("R31 先评后领：评价者本人认领时自评等级作废（标记与事件均不带 impact）",
       _apA.ok and '"impact":"S"' in _apA.comment
       and _cl.ok and bb.latest_marker([_apA.comment, _cl.comment]).get("impact") is None
       and not _cl.event.get("impact"),
       (_apA.ok, _cl.ok, _cl.event.get("impact"),
        bb.latest_marker([_apA.comment, _cl.comment]).get("impact")))
    # 作废必须是**显式留痕**的：`_accept` 里那条按持有者作废是静默的，单看「不带 impact」
    # 无法区分「走了 /claim 专闸」与「被 _accept 兜底吞掉」⇒ 断言必须盯住回避子弹本身。
    ok("R31b 先评后领：作废在该认领评论里**明写回避缘由**（不是静默吞掉）",
       _cl.ok and "由 **@rev1 本人**作出" in _cl.comment
       and "须由非持有者重新 `/appraise`" in _cl.comment and "作废" in _cl.comment,
       _cl.comment[-260:])
    ok("R32 招标中投标人须回避、非投标人不回避（回避面含投标人）",
       bb.needs_recusal(_st271, "rev1")[0] is False
       and bb.needs_recusal(
           bb.IssueState(number=271, labels=_L271, has_bounty=True, state="contest",
                         holder=None, bidders=("rev1",), difficulty="difficulty:hard",
                         author="FuRongJun-1999"), "rev1")[0] is True,
       (bb.needs_recusal(_st271, "rev1"),
        bb.needs_recusal(bb.IssueState(
            number=271, labels=_L271, has_bounty=True, state="contest", holder=None,
            bidders=("rev1",), difficulty="difficulty:hard",
            author="FuRongJun-1999"), "rev1")))
    _st272 = bb.IssueState(number=272, labels=("bounty", "bounty:contest", "difficulty:hard"),
                           has_bounty=True, state="contest", holder=None, rounds=0, seq=1,
                           difficulty="difficulty:hard", author="FuRongJun-1999",
                           bidders=("rev1",))
    _d33 = bb.handle_command(_st272, "/appraise", "S 投标人自评", "/appraise S 投标人自评",
                             "rev1", NOW, CFG, is_maintainer=True)
    ok("R33 招标中投标人 /appraise → 拒（recusal_required，回避含投标人）",
       _d33.ok is False and _d33.event.get("reason", "").startswith("recusal_required"),
       _d33.event.get("reason", ""))
    _st272b = bb.IssueState(number=272, labels=("bounty", "bounty:contest", "difficulty:hard"),
                            has_bounty=True, state="contest", holder=None, rounds=0, seq=1,
                            difficulty="difficulty:hard", author="FuRongJun-1999",
                            bidders=("rev1", "alice"))
    _d33b = bb.handle_command(_st272b, "/select", "alice 别人", "/select alice 别人",
                              "rev1", NOW, CFG, is_maintainer=True)
    ok("R33b 投标人 /select → 拒（recusal_required，定标人不得是投标人）",
       _d33b.ok is False and _d33b.event.get("reason", "").startswith("recusal_required"),
       _d33b.event.get("reason", ""))
    _st273 = bb.IssueState(number=273, labels=("bounty", "bounty:contest", "difficulty:hard"),
                           has_bounty=True, state="contest", holder=None, rounds=0, seq=1,
                           difficulty="difficulty:hard", author="FuRongJun-1999",
                           bidders=("alice", "bob"))
    _st273b = bb.IssueState(number=273, labels=("bounty", "bounty:contest", "difficulty:hard"),
                            has_bounty=True, state="contest", holder=None, rounds=0, seq=1,
                            difficulty="difficulty:hard", author="FuRongJun-1999",
                            bidders=("alice",))
    _d33c = bb.handle_command(_st273b, "/select", "bob 选自己人", "/select bob 选自己人",
                              "bob", NOW, CFG, is_maintainer=True)
    ok("R33c 维护者把标的定给自己 → 拒（recusal_required，自定标禁令）",
       _d33c.ok is False and _d33c.event.get("reason", "").startswith("recusal_required"),
       _d33c.event.get("reason", ""))
    _st274 = bb.IssueState(number=274, labels=("bounty", "bounty:contest", "difficulty:hard"),
                           has_bounty=True, state="contest", holder=None, rounds=0, seq=1,
                           difficulty="difficulty:hard", author="FuRongJun-1999",
                           bidders=("alice", "bob"), impact="S", impact_by="bob")
    _d35s = bb.handle_command(_st274, "/select", "bob 中标", "/select bob 中标",
                              "FuRongJun-1999", NOW, CFG, is_maintainer=True)
    ok("R35 中标者本人的自评等级在定标时作废（不得随人迁移到结算）",
       _d35s.ok and bb.latest_marker([_d35s.comment]).get("impact") is None
       and not _d35s.event.get("impact") and _d35s.holder == "bob",
       (bb.latest_marker([_d35s.comment]).get("impact"), _d35s.event.get("impact")))

    # ---- #404：招标路径被 /verify fail 退回时，被退回的**那份交付**必须计 1 轮 ----
    # #242 定标把 rounds 记 0（G32）；但投标物本身就是第一份交付、维护者可直接 /verify，
    # 退回后轮次若仍为 0，返工交付仍按「一次过闸」记 2×base，与认领路径同形过程不同分。
    _d404f = _bd(_mkb(state="delivered", holder="bob", rounds=0), "/verify",
                 "fail 读数不全", actor="maint1", maint=True)
    ok("R404 定标后第一份交付被 /verify fail ⇒ 该交付计 1 轮（#404）",
       _d404f.ok and _d404f.to_state == "claimed" and _d404f.rounds == 1,
       (_d404f.ok, _d404f.to_state, _d404f.rounds))
    # 反向：定标后**直接 pass** 仍是一次过闸（#198 口径不许被本修复顺手改掉）
    _d404b = _bd(_mkb(state="delivered", holder="bob", rounds=0), "/verify",
                 "pass 读数齐全", actor="maint1", maint=True)
    ok("R404b 定标后直接 pass 仍是一次过闸（rounds=0，不误伤 #198）",
       _d404b.ok and _d404b.to_state == "verified" and _d404b.rounds == 0,
       (_d404b.ok, _d404b.to_state, _d404b.rounds))

    # ---- 价值向量出口（本站只做声誉分与价值评价；金额不进站）----
    def _evv(**kw):
        _e = {"ts": "2026-10-12T01:00:00Z", "action": "settle", "actor": "m", "delta": 0}
        _e.update(kw); _e["id"] = bb.event_id(_e); return _e
    _evs43 = [
        _evv(issue=7, holder="cyd471", difficulty="hard", delta=6, impact="S",
             formula={"rule": "v1.0", "kind": "complete", "base": 6, "rounds": 1,
                      "round": 0, "den": 1, "delta": 6}),
        _evv(issue=8, holder="wasd", difficulty="expert", delta=4, impact="A",
             formula={"rule": "v1.0", "kind": "complete", "base": 10, "rounds": 2,
                      "round": 1, "den": 2, "e_pass": 3, "e_total": 5, "delta": 4}),
        _evv(issue=8, action="lose", holder="bob", actor="bob", difficulty="expert",
             delta=4, formula={"rule": "v1.0", "kind": "lost_bid", "difficulty": "expert",
                               "delta": 4}),
    ]
    _vv43 = bb.value_vector(_evs43, {7: {"project": "memory"}, 8: {"project": "memory"}})
    _rows43 = {r["login"]: r for r in _vv43["vectors"]}
    _keys43 = set()
    for _r in _vv43["vectors"]:
        _keys43 |= set(_r.keys())
    _BAN = {"amount", "money", "cny", "usd", "price", "rate", "weight", "budget",
            "fee", "quota", "fund", "payment"}
    ok("G43 价值向量：按「贡献者×项目」聚合、字段齐、"
       "**且不含任何金额字段**（规格 V2：资金发生在站外，本站只做评价）",
       _rows43["wasd"]["quality_E"] == 0.6 and _rows43["wasd"]["impact_grade"] == "A"
       and _rows43["cyd471"]["difficulty_base"] == 6
       and _rows43["bob"]["reputation_delta"] == 4 and not (_keys43 & _BAN),
       (sorted(_keys43), _rows43.get("wasd")))
    ok("G44 空账本 → 向量为空且不崩，注记保留",
       bb.value_vector([], {})["vectors"] == []
       and "金额不进站" in bb.value_vector([], {})["note"], "")
    _vv45 = bb.value_vector(_evs43, {7: {"project": "memory"}, 8: {"project": "memory"}})
    ok("G45 确定性：同账本两次导出逐字段相同；有 formula 的行 evidence_strength 为真",
       _vv45 == _vv43 and _rows43["wasd"]["evidence_strength"] is True
       and _rows43["cyd471"]["evidence_strength"] is True, _rows43["cyd471"])


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


# 生效条件：同上，但 cfg 由调用方给出——用于真模式读**临时账本**的授权面（I7/I8）。
def _route_cfg(payload, client, cfg, apply=False):
    return bb.handle_issue_comment(payload, cfg, client, apply=apply,
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

    # ---- 真模式授权面：`is_rev` 必须**真的**由账本 role 事件决定（缺陷 #271）----
    # X1/X2 两个变异体（把 is_rev 钉成 True / 只看 cfg.reviewers）在旧套件下**存活**：
    # 没有任何断言走「真模式 + 账本 role」这条路径，授权面等于没有守卫。
    _vst = ('<!-- bounty:v1 {"state":"delivered","holder":"alice",'
            '"rounds":1,"seq":1} -->')
    _led = os.path.join(tempfile.mkdtemp(prefix="bounty_routing_"), "ledger.json")

    cli = _FakeClient(comments=[_vst])
    code, evs = _route_cfg(_issue_payload("/verify pass 读数齐全", actor="zoe"), cli,
                           bb.Config(ledger_path=_led))
    ok("I7 账本无 role ＋ 评论者非维护者 → 真模式 /verify 拒（not_maintainer）",
       code == 0 and evs
       and (evs[0].get("reason") or "").startswith("not_maintainer"),
       (evs[0].get("reason") if evs else None))

    _ev = {"ts": "2026-10-12T00:00:00Z", "issue": 0, "action": "role",
           "actor": "FuRongJun-1999", "subject": "zoe", "role": "reviewer",
           "op": "grant", "reason": "I8 夹具"}
    _ev["id"] = bb.event_id(_ev)
    bb.write_ledger(_led, [_ev])
    cli = _FakeClient(comments=[_vst])
    code, evs = _route_cfg(_issue_payload("/verify pass 读数齐全", actor="zoe"), cli,
                           bb.Config(ledger_path=_led))
    ok("I8 账本 role grant reviewer → 同一评论者真模式 /verify 放行（授权面走账本）",
       code == 0 and evs and evs[0].get("action") == "verify"
       and not (evs[0].get("reason") or "").startswith(("not_maintainer",
                                                        "recusal_required")),
       (evs[0].get("action") if evs else None, evs[0].get("reason") if evs else None))


# ================================================================ [R] 审核员机制

# 生效条件：无必需形参时跑 [R] 组断言——回避闸（自审自结）、审核员档（/verify + /appraise，不含
# /settle）、账本 role 授权面、晋升复合判据。
def group_reviewers():
    print("[R] 审核员机制：回避闸 / 审核员档 / 账本 role 授权面 / 晋升复合判据")

    # --- 回避闸：持有者不得自审自结（对维护者与审核员一律生效）---
    st = mk_state(state="delivered", holder="alice")
    d = bb.handle_command(st, "/verify", "pass 自审", "/verify pass 自审", "alice",
                          NOW, CFG, is_maintainer=True)
    ok("R1 持有者自审 /verify → 拒（recusal_required）",
       (not d.ok) and d.event.get("reason", "").startswith("recusal_required"),
       d.event.get("reason", ""))

    st = mk_state(state="verified", holder="alice")
    d = bb.handle_command(st, "/settle", "", "/settle", "alice", NOW, CFG,
                          is_maintainer=True)
    ok("R2 持有者自结 /settle → 拒（recusal_required）",
       (not d.ok) and d.event.get("reason", "").startswith("recusal_required"),
       d.event.get("reason", ""))

    st = mk_state(state="delivered", holder="alice")
    d = bb.handle_command(st, "/appraise", "A 自评", "/appraise A 自评", "alice",
                          NOW, CFG, is_maintainer=True)
    ok("R3 持有者自评 /appraise → 拒（recusal_required）",
       (not d.ok) and d.event.get("reason", "").startswith("recusal_required"),
       d.event.get("reason", ""))

    st = mk_state(state="delivered", holder="alice")
    d = bb.handle_command(st, "/verify", "pass 读数齐全", "/verify pass 读数齐全",
                          "FuRongJun-1999", NOW, CFG, is_maintainer=True)
    ok("R4 非持有者维护者 /verify → 放行（回避不误伤）",
       d.ok and d.to_state == "verified", str(d.reason))

    ok("R5 无持有者时回避不触发",
       bb.needs_recusal(mk_state(state="open", holder=None), "alice")[0] is False)

    # --- 审核员档：可 /verify 与 /appraise，不含 /settle ---
    st = mk_state(state="delivered", holder="alice")
    d = bb.handle_command(st, "/verify", "pass 审核员判定", "/verify pass 审核员判定",
                          "rev1", NOW, CFG, is_reviewer=True)
    ok("R6 审核员 /verify → 放行", d.ok and d.to_state == "verified", str(d.reason))

    st = mk_state(state="delivered", holder="alice")
    d = bb.handle_command(st, "/appraise", "A 审核员评价", "/appraise A 审核员评价",
                          "rev1", NOW, CFG, is_reviewer=True)
    ok("R7 审核员 /appraise → 放行",
       d.ok and d.event.get("impact") == "A", str(d.event.get("impact")))

    st = mk_state(state="verified", holder="alice")
    d = bb.handle_command(st, "/settle", "", "/settle", "rev1", NOW, CFG,
                          is_reviewer=True)
    ok("R8 审核员 /settle → 拒（审核员档**不含**结算）",
       (not d.ok) and d.event.get("reason", "").startswith("not_maintainer"),
       d.event.get("reason", ""))

    st = mk_state(state="delivered", holder="alice")
    d = bb.handle_command(st, "/verify", "pass 路人", "/verify pass 路人", "bob",
                          NOW, CFG)
    ok("R9 非维护者非审核员 /verify → 拒（not_maintainer）",
       (not d.ok) and d.event.get("reason", "").startswith("not_maintainer"),
       d.event.get("reason", ""))

    st = mk_state(state="delivered", holder="rev1")
    d = bb.handle_command(st, "/verify", "pass 自审", "/verify pass 自审", "rev1",
                          NOW, CFG, is_reviewer=True)
    ok("R10 审核员对自持 issue /verify → 仍拒（回避优先于授权）",
       (not d.ok) and d.event.get("reason", "").startswith("recusal_required"),
       d.event.get("reason", ""))

    # --- 账本 role 授权面（append-only；同一主体以时间最晚的一条为准）---
    def _role(sub, role="reviewer", op="grant", ts="2026-10-12T00:00:00Z"):
        return {"ts": ts, "action": "role", "actor": "FuRongJun-1999",
                "subject": sub, "role": role, "op": op, "reason": "守卫夹具"}

    ok("R11 role grant → 进审核员面",
       "rev1" in bb.roles_from_events([_role("rev1")])["reviewer"])
    ok("R12 role revoke（更晚）→ 移出审核员面",
       "rev1" not in bb.roles_from_events(
           [_role("rev1"), _role("rev1", op="revoke", ts="2026-10-12T01:00:00Z")]
           )["reviewer"])
    ok("R13 后事件覆盖前事件（以时间最晚为准）",
       "rev1" not in bb.roles_from_events(
           [_role("rev1", op="revoke", ts="2026-10-12T01:00:00Z"), _role("rev1")]
           )["reviewer"])
    ok("R14 越界 role/op → 跳过（不猜测）",
       "rev1" not in bb.roles_from_events(
           [_role("rev1", role="superuser"), _role("rev1", op="maybe")])["reviewer"])
    ok("R15 缺 subject → 跳过",
       bb.roles_from_events([{"action": "role", "subject": "", "role": "reviewer",
                              "op": "grant"}])["reviewer"] == {})
    ok("R16 非 role 事件不进授权面",
       bb.roles_from_events([{"action": "settle", "subject": "rev1",
                              "role": "reviewer", "op": "grant"}])["reviewer"] == {})

    # --- 晋升复合判据 ---
    def _sev(who, delta, rnd=0, kind="complete", ino=1):
        return {"ts": "2026-10-12T00:00:00Z", "issue": ino, "action": "settle",
                "actor": "FuRongJun-1999", "holder": who, "delta": delta,
                "formula": {"kind": kind, "round": rnd}}

    def _pick(rep, who):
        return [c for c in rep["candidates"] if c["login"] == who][0]

    rep = bb.promotion_report([_sev("good", 20, 0, ino=1), _sev("good", 20, 0, ino=2)])
    g = _pick(rep, "good")
    ok("R17 复合判据达标 → eligible=True", g["eligible"] is True, str(g["blockers"]))
    ok("R18 一次过闸占比算出（2/2 = 1.0）", g["round0_ratio"] == 1.0)

    rep = bb.promotion_report([_sev("bad", 20, 0, ino=1), _sev("bad", 20, 0, ino=2),
                               _sev("bad", -6, 0, kind="invalid", ino=3)])
    b = _pick(rep, "bad")
    ok("R19 无效交付 → 阻塞（负向记录一票否决）",
       b["eligible"] is False and any("无效交付" in x for x in b["blockers"]),
       str(b["blockers"]))

    rep = bb.promotion_report([_sev("rework", 20, 2, ino=1), _sev("rework", 20, 2, ino=2)])
    n = _pick(rep, "rework")
    ok("R20 有 round 数据但过闸占比不达标 → 阻塞",
       n["eligible"] is False and any("一次过闸" in x for x in n["blockers"]),
       str(n["blockers"]))

    rep = bb.promotion_report([{"ts": "2026-10-12T00:00:00Z", "issue": 1,
                                "action": "settle", "actor": "m", "holder": "noround",
                                "delta": 20}])
    nr = _pick(rep, "noround")
    ok("R21 无 round 数据 → **不阻塞**（该条判据不适用）",
       not any("一次过闸" in x for x in nr["blockers"]), str(nr["blockers"]))
    ok("R22 无 round 数据 → 记证据缺口（不静默）",
       any("无 round 数据" in x for x in nr["evidence_gaps"]),
       str(nr["evidence_gaps"]))
    ok("R23 无 round 数据时 round0_ratio=None", nr["round0_ratio"] is None)

    rep = bb.promotion_report([_sev("low", 3, 0, ino=1)])
    lo = _pick(rep, "low")
    ok("R24 声誉分与项数双不达标 → 阻塞",
       lo["eligible"] is False and len(lo["blockers"]) >= 2, str(lo["blockers"]))

    rep = bb.promotion_report([_sev("t", -6, 0, kind="timeout", ino=1)])
    tt = _pick(rep, "t")
    ok("R25 超时未交付 → 阻塞",
       tt["eligible"] is False and any("超时" in x for x in tt["blockers"]),
       str(tt["blockers"]))

    ok("R26 报告带判据表快照（可审计）", rep["rules"] == dict(bb.PROMOTION_RULES))
    ok("R27 判据表与实现同源（非硬编码副本）",
       bb.PROMOTION_RULES["min_reputation"] == rep["rules"]["min_reputation"])

    rep = bb.promotion_report([_sev("flat", 20, 1, ino=1), _sev("flat", 20, 1, ino=2)])
    fl = _pick(rep, "flat")
    ok("R28 round 全为中性占位 → 该维度不适用（不阻塞）",
       fl["eligible"] is True and not any("一次过闸" in x for x in fl["blockers"]),
       str(fl["blockers"]))
    ok("R29 无区分度 → 记证据缺口（不静默）",
       any("无区分度" in x for x in fl["evidence_gaps"]),
       str(fl["evidence_gaps"]))
    ok("R29b round_seen 快照可审计（[1]）", fl["round_seen"] == [1])
    rep = bb.promotion_report([_sev("mix", 20, 0, ino=1), _sev("mix", 20, 2, ino=2),
                               _sev("mix", 20, 2, ino=3), _sev("mix", 20, 2, ino=4)])
    mx = _pick(rep, "mix")
    ok("R30 出现 round=0/>=2 → 有区分度，判据自动生效",
       mx["eligible"] is False and any("一次过闸" in x for x in mx["blockers"]),
       str(mx["blockers"]))
    # ---- ★本笔新增（缺陷 #267：轮次来源可辨 ⇒ 判据单调）----
    def _live(who, delta, rnd, ino):
        return {"ts": "2026-10-12T00:00:00Z", "issue": ino, "action": "settle",
                "actor": "m", "holder": who, "delta": delta,
                "formula": {"kind": "complete", "round": rnd, "mode": "live"}}
    rep = bb.promotion_report([_live("lx", 20, 1, i) for i in (1, 2, 3, 4)])
    lx = _pick(rep, "lx")
    ok("R36 真模式 round=1（返工一次）计入占比分母 ⇒ 阻塞（不再当占位）",
       lx["eligible"] is False and any("一次过闸" in x for x in lx["blockers"]),
       str(lx["blockers"]))
    ok("R37 轮次来源可审计（round0_ratio_source=live）",
       lx.get("round0_ratio_source") == "live", lx.get("round0_ratio_source"))
    _xr = [_live("xr", 20, 1, i) for i in (1, 2, 3, 4)]
    _yr = [_live("yr", 30, 0, 5)] + [_live("yr", 20, 1, i) for i in (6, 7, 8)]
    rep = bb.promotion_report(_xr + _yr)
    xg = _pick(rep, "xr")
    yg = _pick(rep, "yr")
    ok("R38 单调性：全返工者（低分）与偶尔一次过闸者（高分）**都不得达标**"
       "——修前低分者反被判「无区分度」而达标（判据非单调、可博弈）",
       xg["eligible"] is False and yg["eligible"] is False,
       (xg["eligible"], str(xg["blockers"]), yg["eligible"], str(yg["blockers"])))
    rep = bb.promotion_report([_live("mix2", 20, 0, 1), _sev("mix2", 20, 2, ino=2)])
    m2 = _pick(rep, "mix2")
    ok("R39 live 与追溯混合 ⇒ 只用 live 算占比，追溯事件记缺口（不进分母）",
       m2["round0_ratio"] == 1.0 and m2.get("round0_ratio_source") == "live"
       and any("追溯性结算" in x for x in m2["evidence_gaps"]),
       (m2["round0_ratio"], m2["evidence_gaps"]))
    _st267 = mk_state(state="verified", holder="solo")
    _d267 = bb._do_settle(_st267, "FuRongJun-1999", NOW, CFG, is_maintainer=True)
    ok("R40 真模式 /settle 的 formula 带 mode=live（轮次来源可辨，非默认）",
       _d267.ok is True and (_d267.event.get("formula") or {}).get("mode") == "live",
       (_d267.event.get("formula") or {}).get("mode"))

    # ---- ★本笔新增（缺陷 #268：账本 role 是权威面）----
    def _role_ev(sub, role, op, ts):
        e = {"ts": ts, "issue": 0, "action": "role", "actor": "FuRongJun-1999",
             "subject": sub, "role": role, "op": op, "reason": "夹具"}
        e["id"] = bb.event_id(e)
        return e
    _rv = bb.role_revocations([_role_ev("rev1", "reviewer", "grant", "2026-10-12T00:00:00Z"),
                               _role_ev("rev1", "reviewer", "revoke", "2026-10-12T01:00:00Z")])
    ok("R41 账本最新态为 revoke → 进撤销集",
       "rev1" in _rv["reviewer"], sorted(_rv["reviewer"]))
    _rv2 = bb.role_revocations([_role_ev("g1", "maintainer", "grant", "2026-10-12T00:00:00Z")])
    ok("R42 账本最新态为 grant → 不在撤销集",
       "g1" not in _rv2["maintainer"], sorted(_rv2["maintainer"]))
    _rv3 = bb.role_revocations([_role_ev("r2", "reviewer", "revoke", "2026-10-12T00:00:00Z"),
                                _role_ev("r2", "reviewer", "grant", "2026-10-12T01:00:00Z")])
    ok("R43 撤销后再授予 → 以最晚一条为准（不在撤销集）",
       "r2" not in _rv3["reviewer"], sorted(_rv3["reviewer"]))
    _vst268 = '<!-- bounty:v1 {"state":"delivered","holder":"zoe","rounds":1,"seq":1} -->'
    _l1 = os.path.join(tempfile.mkdtemp(prefix="bounty_r268_"), "ledger.json")
    bb.write_ledger(_l1, [_role_ev("rev1", "reviewer", "grant", "2026-10-12T00:00:00Z"),
                          _role_ev("rev1", "reviewer", "revoke", "2026-10-12T01:00:00Z")])
    _c1, _e1 = _route_cfg(_issue_payload("/verify pass 读数齐全", actor="rev1"),
                          _FakeClient(comments=[_vst268]),
                          bb.Config(reviewers=("rev1",), ledger_path=_l1))
    ok("R44 启动面名单里的审核员被账本 revoke ⇒ 真模式 /verify 拒（撤销以账本为准）",
       _e1 and (_e1[0].get("reason") or "").startswith("not_maintainer"),
       (_e1[0].get("reason") if _e1 else None))
    _l2 = os.path.join(tempfile.mkdtemp(prefix="bounty_r268b_"), "ledger.json")
    bb.write_ledger(_l2, [_role_ev("mt2", "maintainer", "grant", "2026-10-12T00:00:00Z")])
    _c2, _e2 = _route_cfg(_issue_payload("/verify pass 读数齐全", actor="mt2"),
                          _FakeClient(comments=[_vst268]),
                          bb.Config(ledger_path=_l2))
    ok("R45 账本 grant maintainer ⇒ 真模式 /verify 放行（不再是死数据）",
       _e2 and _e2[0].get("action") == "verify",
       (_e2[0].get("action") if _e2 else None, _e2[0].get("reason") if _e2 else None))
    bb.write_ledger(_l2, [_role_ev("mt2", "maintainer", "grant", "2026-10-12T00:00:00Z"),
                          _role_ev("mt2", "maintainer", "revoke", "2026-10-12T01:00:00Z")])
    _c3, _e3 = _route_cfg(_issue_payload("/verify pass 读数齐全", actor="mt2", assoc="COLLABORATOR"),
                          _FakeClient(comments=[_vst268]),
                          bb.Config(ledger_path=_l2))
    ok("R46 账本 revoke 不撤销 GitHub 关联身份（平台事实 ≠ 站内授权）",
       _e3 and _e3[0].get("action") == "verify",
       (_e3[0].get("action") if _e3 else None, _e3[0].get("reason") if _e3 else None))
    _c4, _e4 = _route_cfg(_issue_payload("/verify pass 读数齐全", actor="mt2"),
                          _FakeClient(comments=[_vst268]),
                          bb.Config(maintainers=("mt2",), ledger_path=_l2))
    ok("R47 启动面维护者被账本 revoke ⇒ /verify 拒（无平台身份时撤销生效）",
       _e4 and (_e4[0].get("reason") or "").startswith("not_maintainer"),
       (_e4[0].get("reason") if _e4 else None))

# --- 准入闸：悬赏只能由维护者发布（标签闸之外的第二道；作者是兜底）---
def group_admission():
    def _st(author, labels=("bounty", "bounty:open")):
        return bb.build_state(1, labels, (), author=author)

    d = claim(_st("FuRongJun-1999"))
    ok("Z1 维护者发布的悬赏 → 外部人可认领", d.ok and d.to_state == "claimed", d.reason)

    d = claim(_st("outsider"))
    ok("Z2 外部人发布的 issue（带 bounty 标签）→ 拒（not_admitted）",
       d.ok is False and "不在维护者名单内" in d.reason, d.reason)

    d = claim(_st(None))
    ok("Z3 作者未知（None）→ 拒（fail-closed，理由含「无法确认」）",
       d.ok is False and "无法确认" in d.reason, d.reason)

    d = claim(_st("outsider", ("bounty:open",)))
    ok("Z4 准入闸先于标签闸（外部人发布 + 无 bounty 标签 → 理由为作者而非标签）",
       d.ok is False and "不在维护者名单内" in d.reason and "没有" not in d.reason, d.reason)

    d = claim(_st("FuRongJun-1999", ("bounty:open",)))
    ok("Z5 维护者发布但无 bounty 标签 → 仍拒（标签闸独立生效）",
       d.ok is False and "bounty" in d.reason and "不在维护者名单内" not in d.reason, d.reason)

    # ---- 招标侧（`/bid` `/select`）与认领侧共用同一准入闸：否则外部人发一条带
    #      bounty:contest 的 issue 就能招标、产生中标者并被结算（缺陷 #270B）----
    def _bidder(author, labels):
        return bb.IssueState(number=1, labels=tuple(labels),
                             has_bounty="bounty" in labels, state="contest",
                             holder=None, rounds=0, seq=1,
                             difficulty="difficulty:hard", author=author, bidders=())

    _L_contest = ("bounty", "bounty:contest", "difficulty:hard")
    d = bb.handle_command(_bidder("outsider", _L_contest), "/bid",
                          "https://example.com/pull/1", "/bid https://example.com/pull/1",
                          "zoe", NOW, CFG)
    ok("Z6 外部人发布的招标 /bid → 拒（not_admitted）",
       d.ok is False and d.event.get("reason", "").startswith("not_admitted"),
       d.event.get("reason", ""))

    d = bb.handle_command(_bidder("FuRongJun-1999", ("bounty:contest", "difficulty:hard")),
                          "/bid", "https://example.com/pull/1",
                          "/bid https://example.com/pull/1", "zoe", NOW, CFG)
    ok("Z7 缺 bounty 标签的招标 /bid → 拒（state_not_claimable）",
       d.ok is False and d.event.get("reason", "").startswith("state_not_claimable"),
       d.event.get("reason", ""))

    d = bb.handle_command(_bidder("outsider", _L_contest), "/select", "zoe 定标",
                          "/select zoe 定标", "FuRongJun-1999", NOW, CFG,
                          is_maintainer=True)
    ok("Z8 外部人发布的招标 /select 同拒（not_admitted，招标两侧共闸）",
       d.ok is False and d.event.get("reason", "").startswith("not_admitted"),
       d.event.get("reason", ""))


_GROUPS = (group_admission, group_parse, group_label_state, group_holder, group_concurrency,
           group_is_holder, group_payload, group_lifecycle, group_routing,
           group_reviewers)


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
     "    if False:  # MUT", {"B1", "Z5", "Z7"}),
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
     "    if False:  # MUT", {"G7", "G19", "G20", "G23", "G24", "G26", "R40"}),
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
# ⚠ 本 PR 改了 `rescore` 的 `_e` 取法（内联 ⇒ `e_ratio` 单点），故 M18 的锚点必须
# 同步更新——否则 `_anchor_preflight()` 会以 ANCHOR-MISS 退出码 2（fail-closed）拒掉本 PR。
# 这是本仓既有纪律（`_mutate_source` 的锚点唯一性），不是放宽判据：M18 的语义
# （关掉 E 乘数 ⇒ 复算链与结算口径分叉）与期望红项 `{"G24"}` 均未变。
    ("M18 rescore 忽略 E（复算链与结算口径分叉）",
     "            _e = e_ratio(f.get(\"e_pass\"), f.get(\"e_total\"))",
     "            _e = 1.0  # MUT", {"G24", "G47", "G48"}),
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
     "    if False:  # MUT" + chr(10) + '        marker["impact"] = _im',
     {"G37", "G42", "R31", "R31b"}),
    ("M29 关价值评价的维护者闸（越权可评）",
     "    if not (is_maintainer or is_reviewer):",
     "    if False:  # MUT", {"G40"}),
    ("M30 向价值向量注入金额字段（越界）",
     "    out.sort(key=lambda r: (-r[\"reputation_delta\"], r[\"login\"], r[\"project\"]))",
     "    out.sort(key=lambda r: (-r[\"reputation_delta\"], r[\"login\"], r[\"project\"]))" + chr(10) + "    for _r in out:" + chr(10) + "        _r[\"amount\"] = _r[\"reputation_delta\"]  # MUT", {"G43"}),
    ("M31 关证据强度判据（formula 凭据不计）",
     "        row[\"evidence_strength\"] = bool(row.pop(\"_f\"))",
     "        row.pop(\"_f\", None)" + chr(10) + "        row[\"evidence_strength\"] = False  # MUT", {"G45"}),
     ("M32 关 /verify 回避闸（持有者可自审）",
      '    _rec, _why = needs_recusal(st, actor)',
      '    _rec, _why = (False, "")  # MUT', {"R1", "R10"}),
     ("M33 关 /verify 审核员档（审核员不可裁）",
      '    if not (is_maintainer or is_reviewer):',
      '    if not is_maintainer:  # MUT', {"R6", "I8"}),
     ("M34 关 /settle 授权闸（审核员可结算）",
      '    if not is_maintainer:',
      '    if False:  # MUT', {"G5", "R8"}),
     ("M35 关 /settle 回避闸（持有者可自结）",
      '    _rec, _why = needs_recusal(st, actor)',
      '    _rec, _why = (False, "")  # MUT', {"R2"}),
     ("M36 关 /appraise 回避闸（持有者可自评）",
      '    _rec, _why = needs_recusal(st, actor)',
      '    _rec, _why = (False, "")  # MUT', {"R3", "R33"}),
     ("M37 授权面不认 revoke（撤销无效）",
      '        if info["op"] == "grant":',
      '        if True:  # MUT', {"R12", "R13"}),
     ("M38 无 round 数据不记「不适用」缺口",
      '        elif not row["round_known"]:' + chr(10) + '            gaps.append("无 round 数据（一次过闸占比不可判）——该条判据不适用")',
      '        elif False:  # MUT' + chr(10) + '            gaps.append("无 round 数据（一次过闸占比不可判）——该条判据不适用")', {"R22"}),
     ("M39 无效交付不阻塞晋升",
      '        if row["invalid"] > R["max_invalid"]:',
      '        if False:  # MUT', {"R19"}),
     ("M40 关区分度判据（中性占位也按占比判）",
      '        elif len(row["round_seen"] - {1}) == 0:',
      '        elif False:  # MUT', {"R28", "R29"}),
    ("M41 关作者闸（外部人发布的 issue 可被认领）",
     '    if st.author not in cfg.maintainers:',
     '    if False:  # MUT', {"Z2", "Z4", "Z6", "Z8"}),
    ("M42 关作者缺失检查（作者 None 也放行到名单比对）",
     '    if not st.author:',
     '    if False:  # MUT', {"Z3"}),
    # ★本笔新增：关掉 `rescore` 的畸形输入兜底 ⇒ 畸形 formula 会**抛裸 ValueError**
    # （旧实现即如此：`int("abc")` 直接回溯，既不落 `BoardError` 也不返回 bad 报告）。
    ("M43 rescore 不兜底畸形 formula（畸形输入直接抛）",
     '        except (TypeError, ValueError, ZeroDivisionError) as exc:',
     '        except (KeyboardInterrupt,) as exc:  # MUT', {"G46", "G47", "G48"}),
    # ★本笔新增：`_as_int` 不再宽容（非法值直接抛）⇒ 畸形 delta 会崩。
    ("M44 `_as_int` 不宽容（非法值直接抛）",
     '    try:' + chr(10) + '        return int(x)' + chr(10) + '    except (TypeError, ValueError):' + chr(10) + '        return default',
     '    return int(x)  # MUT', {"G49", "G51"}),
    # ---- ★本笔新增（缺陷 #270：招标侧准入/标签闸）----
    ("M45 关招标作者闸（外部人发布的招标可被投标）",
     '    ok_adm, why_adm = _check_admission(st, cfg)',
     '    ok_adm, why_adm = (True, "")  # MUT', {"Z6", "Z8"}),
    ("M46 关招标标签闸（缺 `bounty` 标签也放行投标/定标）",
     '    ok_lbl, why_lbl = _check_bounty_label(st)',
     '    ok_lbl, why_lbl = (True, "")  # MUT', {"Z7"}),
    # ---- ★本笔新增（缺陷 #269B/C：投标人回避）----
    ("M47 关 /select 的投标人回避（投标人可参与定标）",
     '    _rec, _why = needs_recusal(st, actor)',
     '    _rec, _why = (False, "")  # MUT', {"G35", "R33b"}),
    ("M48 关 needs_recusal 的投标人回避（招标中投标人可自评）",
     '    if actor and st.state == "contest" and actor in (st.bidders or ()):',
     '    if False:  # MUT', {"R32", "R33", "R33b"}),
    ("M49 关 /select 的自定标闸（定标人可把标定给自己）",
     '    if winner == actor:',
     '    if False:  # MUT', {"R33c"}),
    # ---- ★本笔新增（缺陷 #269A：自评等级不得随持有者迁移）----
    ("M50 不隔离随人迁移的自评等级（等级可迁移到新持有者/执行者）",
     '    if _im and _ib and action != "/appraise" and _ib in (holder, actor):',
     '    if False:  # MUT', {"R31", "R35"}),
    ("M51 关真模式审核员面（账本 role 授权失效）",
     "    is_rev = actor in cfg.reviewers or actor in _roles['reviewer']",
     '    is_rev = actor in cfg.reviewers  # MUT', {"I8"}),
    # ---- ★本笔新增（缺陷 #267 轮次来源可辨 / #268 账本 role 是权威面）----
    ("M52 关账本 revoke 对审核员面的撤销（启动面名单撤销失效）",
     "    is_rev = is_rev and actor not in _revoked['reviewer']",
     '    is_rev = is_rev  # MUT', {"R44"}),
    ("M53 关账本 grant maintainer 的授权（角色只导出、不授权）",
     "                or actor in _roles['maintainer']",
     '                or False  # MUT', {"R45"}),
    ("M54 关账本 revoke 对维护者面的撤销",
     "        is_maint = is_maint and actor not in _revoked['maintainer']",
     '        is_maint = is_maint  # MUT', {"R47"}),
    ("M55 关「轮次来源可辨」分支（把追溯占位与真轮次混算）",
     '        if row["live_known"]:',
     '        if False:  # MUT', {"R36", "R37", "R38", "R39"}),
    ("M56 关 role_revocations 的撤销收集（撤销集恒空）",
     '        if op == "revoke":',
     '        if False:  # MUT', {"R41", "R44", "R47"}),
    ("M57 不打轮次来源标记（formula 无 mode）",
     '    formula = dict(formula or {}, mode=ROUND_MODE_LIVE)',
     '    formula = formula  # MUT', {"R40"}),
    # ---- ★本笔新增（缺陷 #404：招标路径被退回时轮次爆 0）----
    ("M59 fail 分支退回时不兜底计 1 轮（定标投标物的轮次爆 0）",
     '        _rounds = max(st.rounds, 1)',
     '        _rounds = st.rounds  # MUT', {"R404"}),
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
_MUT_TARGETS = (("M0", "parse_command"), ("M1", "_check_bounty_label"),
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
                ("M28", "_accept"), ("M29", "_do_appraise"),
                ("M30", "value_vector"), ("M31", "value_vector"),
                ("M32", "_do_verify"), ("M33", "_do_verify"),
                ("M34", "_do_settle"), ("M35", "_do_settle"),
                ("M36", "_do_appraise"), ("M37", "roles_from_events"),
                ("M38", "promotion_report"), ("M39", "promotion_report"),
                ("M40", "promotion_report"),
                ("M41", "_check_admission"), ("M42", "_check_admission"),
                ("M43", "rescore"), ("M44", "_as_int"),
                ("M45", "_guard_admitted_bounty"), ("M46", "_guard_admitted_bounty"),
                ("M47", "_do_select"), ("M48", "needs_recusal"),
                ("M49", "_do_select"), ("M50", "_accept"),
                ("M51", "handle_issue_comment"),
                ("M52", "handle_issue_comment"), ("M53", "handle_issue_comment"),
                ("M54", "handle_issue_comment"), ("M55", "promotion_report"),
                ("M56", "role_revocations"), ("M57", "_do_settle"),
                ("M59", "_do_verify"))


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
