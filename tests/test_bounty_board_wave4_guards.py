# -*- coding: utf-8 -*-
"""守卫 · bounty_board 线上路由 / URL 提取 / 复算 / 批内去重 / 并发去重（正向 ＋ 定点变异自证）。

  python -X utf8 tests/test_bounty_board_wave4_guards.py            # 正向断言
  python -X utf8 tests/test_bounty_board_wave4_guards.py --mutate   # 定点变异自证（纯内存/临时副本，零写仓）

覆盖六项确定性缺陷：
  W1  apply_live 落盘事件包含 dec.extra_events（/select 落选分事件不再在真模式静默丢失）
  W2  extract_pr_number 严格校验 scheme/host/path（阻断 evil.com/github.com/...、notgithub.com、query/blob 伪造）
  W3  handle_issue_comment 对 /bid 同样提取本仓 PR 元数据（对齐 _do_bid 的 pr_meta 参数）
  W4  rescore 对非对象 formula（#644）、bool/非整数 delta/base、负 round、未知 kind 全部 fail-closed 报错
  W5  append_events 批内按 id 幂等去重（#31）且容忍非对象元素
  W6  GitHubClient.count_active_claims 按 issue 号去重（#2438，双标签不再重复计数）
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BB_PATH = os.path.join(ROOT, "scripts", "bounty_board.py")
REAL_LEDGER = os.path.join(ROOT, "docs", "bounty", "ledger.json")


def _load_bb(path: str, mod_name: str = "bb_wave4_target"):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_suite(bb, quiet: bool = False):
    red = []
    total = [0]

    def ok(code: str, desc: str, cond: bool, detail=""):
        total[0] += 1
        if not cond:
            red.append(code)
        if not quiet:
            tail = f"  · {detail!r}" if (not cond and detail != "") else ""
            print(f"  [{'PASS' if cond else 'FAIL'}] {code} {desc}{tail}")

    # ---- W1: apply_live preserves dec.extra_events ----
    st_c = bb.IssueState(
        number=10,
        labels=("bounty", "bounty:contest", "difficulty:hard"),
        has_bounty=True,
        state="contest",
        author="FuRongJun-1999",
        bidders=("alice", "bob", "carol"),
    )
    dec_sel = bb.handle_command(
        st_c, "/select", "alice best", "/select alice best",
        "FuRongJun-1999", bb.parse_ts("2026-11-25T12:00:00Z"),
        bb.Config(), is_maintainer=True,
    )
    evts = bb.apply_live(None, [st_c], [dec_sel], apply=False, out=lambda *_a: None)
    ok("W1a", "apply_live 保留 dec.extra_events（/select 含 2 条 lose 事件）",
       len(dec_sel.extra_events) == 2 and len(evts) == 3
       and [e.get("action") for e in evts] == ["select", "lose", "lose"],
       [e.get("action") for e in evts])
    ok("W1b", "apply_live 事件集合与 store_apply 一致",
       {e.get("id") for e in evts} == {dec_sel.event["id"]} | {e["id"] for e in dec_sel.extra_events})

    # ---- W2: extract_pr_number host/path hardening ----
    repo = "FuRongJun-1999/dsh-bounty"
    ok("W2a", "合法本仓 PR 链接（含大小写/子路径/查询串）照常提取",
       bb.extract_pr_number("https://github.com/FuRongJun-1999/dsh-bounty/pull/77", repo) == 77
       and bb.extract_pr_number("https://GITHUB.COM/furongjun-1999/DSH-BOUNTY/pull/88/files?w=1", repo) == 88)
    spoofs = [
        "https://evil.com/github.com/FuRongJun-1999/dsh-bounty/pull/77",
        "https://notgithub.com/FuRongJun-1999/dsh-bounty/pull/77",
        "https://github.com.evil.com/FuRongJun-1999/dsh-bounty/pull/77",
        "https://github.com:8443/FuRongJun-1999/dsh-bounty/pull/77",
        "https://user@github.com/FuRongJun-1999/dsh-bounty/pull/77",
        "https://github.com/FuRongJun-1999/dsh-bounty/issues/1?x=/pull/77",
        "https://github.com/FuRongJun-1999/dsh-bounty/blob/main/pull/77",
        "https://github.com/other/dsh-bounty/pull/77",
    ]
    got_spoofs = [bb.extract_pr_number(u, repo) for u in spoofs]
    ok("W2b", "全部 8 类伪造/非本仓 PR 链接一律返回 None",
       all(x is None for x in got_spoofs), got_spoofs)

    # ---- W3: handle_issue_comment extracts pr_meta on /bid ----
    class _BidClient:
        repo = "FuRongJun-1999/dsh-bounty"
        labels_ready = True
        def __init__(self):
            self.pulled = []
        def comments(self, _n):
            return []
        def pull(self, n):
            self.pulled.append(n)
            return {"title": "bid PR", "state": "open", "head": {"sha": "abcdef1234567890"}}
        def count_active_claims(self, _actor, exclude=None):
            return 0
        def ensure_labels(self, _specs):
            return []
        def set_labels(self, *_a):
            pass
        def comment(self, *_a):
            pass

    bc = _BidClient()
    bid_payload = {
        "issue": {
            "number": 55,
            "labels": [{"name": "bounty"}, {"name": "bounty:contest"}, {"name": "difficulty:medium"}],
            "user": {"login": "FuRongJun-1999"},
        },
        "comment": {
            "body": "/bid https://github.com/FuRongJun-1999/dsh-bounty/pull/99",
            "user": {"login": "alice"},
            "author_association": "NONE",
        },
    }
    rc_b, ev_b = bb.handle_issue_comment(bid_payload, bb.Config(ledger_path="__nonexistent__"),
                                         bc, apply=False, out=lambda *_a: None)
    ok("W3a", "真模式 /bid 提取并附带本仓 pr 元数据",
       rc_b == 0 and bc.pulled == [99] and len(ev_b) == 1
       and (ev_b[0].get("pr") or {}).get("number") == 99,
       (bc.pulled, ev_b[0].get("pr") if ev_b else None))

    # ---- W4: rescore fail-closed on non-dict formula, bool/str delta/base, neg round, unknown kind ----
    try:
        r_str_f = bb.rescore([{"id": "evt_fstr", "delta": 40, "formula": "manual note"}])
    except Exception as exc:
        r_str_f = ("CRASH", type(exc).__name__)
    ok("W4a", "rescore 对非对象 formula 不崩、点名 malformed formula（#644）",
       r_str_f[0] is False and len(r_str_f[1]) == 1 and r_str_f[1][0][1].startswith("malformed formula"),
       r_str_f)

    r_miss_str = bb.rescore([{"id": "evt_ms", "delta": "abc"}])
    r_miss_bool = bb.rescore([{"id": "evt_mb", "delta": False}])
    r_miss_ok = bb.rescore([{"id": "evt_m0", "delta": 0, "formula": None}])
    ok("W4b", "rescore 缺 formula 时拒绝非整数/bool delta，合法 delta=0 照常通过",
       r_miss_str[0] is False and r_miss_bool[0] is False and r_miss_ok[0] is True,
       (r_miss_str, r_miss_bool, r_miss_ok))

    r_dr_bad = bb.rescore([{"id": "evt_dr", "delta": "xyz",
                            "formula": {"rule": "maintainer_direct_ruling", "base": "abc"}}])
    r_dr_bool = bb.rescore([{"id": "evt_drb", "delta": True,
                             "formula": {"rule": "maintainer_direct_ruling", "base": 1}}])
    r_dr_ok = bb.rescore([{"id": "evt_drok", "delta": 40,
                           "formula": {"rule": "maintainer_direct_ruling", "base": 40}}])
    ok("W4c", "rescore 维护者直裁拒绝非整数/bool base 或 delta，合法直裁通过",
       r_dr_bad[0] is False and r_dr_bool[0] is False and r_dr_ok[0] is True,
       (r_dr_bad, r_dr_bool, r_dr_ok))

    r_bool_d = bb.rescore([{"id": "evt_bd", "delta": True,
                            "formula": {"rule": "v1.0", "kind": "complete", "base": 1, "round": 1}}])
    r_zero_str = bb.rescore([{"id": "evt_z0", "delta": "abc",
                              "formula": {"rule": "v1.0", "kind": "lost_bid", "difficulty": "easy"}}])
    ok("W4d", "rescore 拒绝 bool delta 与 d==0 下的非整数 delta",
       r_bool_d[0] is False and r_zero_str[0] is False, (r_bool_d, r_zero_str))

    r_neg = bb.rescore([{"id": "evt_nr", "delta": 1,
                         "formula": {"rule": "v1.0", "kind": "complete", "base": 3, "round": -2}}])
    r_unk = bb.rescore([{"id": "evt_uk", "delta": 1,
                         "formula": {"rule": "v1.0", "kind": "bogus_kind", "base": 1, "round": 1}}])
    ok("W4e", "rescore 拒绝负 round 与未知 kind（malformed formula）",
       r_neg[0] is False and r_unk[0] is False
       and r_neg[1][0][1].startswith("malformed formula")
       and r_unk[1][0][1].startswith("malformed formula"),
       (r_neg, r_unk))

    real_evs = json.load(io.open(REAL_LEDGER, encoding="utf-8"))["events"]
    r_real = bb.rescore(real_evs)
    ok("W4f", "真实账本全量 rescore 保持 ok=True", r_real[0] is True and not r_real[1], len(r_real[1]))

    # ---- W5: append_events intra-batch dedup (#31) ----
    e1 = {"id": "evt_dup_1", "delta": 3}
    e2 = {"id": "evt_dup_2", "delta": 6}
    merged = bb.append_events([], [e1, dict(e1), "bad", e2, dict(e2)])
    ok("W5a", "append_events 批内重复事件按 id 去重且跳过非对象（#31）",
       len(merged) == 2 and [e["id"] for e in merged] == ["evt_dup_1", "evt_dup_2"],
       merged)

    # ---- W6: GitHubClient.count_active_claims dual-label dedup (#2438) ----
    class _DualLabelClient(bb.GitHubClient):
        def __init__(self):
            pass
        def issues_with_label(self, label, limit=10):
            return [
                {"number": 42,
                 "labels": [{"name": "bounty"}, {"name": "bounty:claimed"}, {"name": "bounty:delivered"}],
                 "user": {"login": "FuRongJun-1999"}},
                {"number": 43,
                 "labels": [{"name": "bounty"}, {"name": "bounty:claimed"}],
                 "user": {"login": "FuRongJun-1999"}},
            ] if label == "bounty:claimed" else [
                {"number": 42,
                 "labels": [{"name": "bounty"}, {"name": "bounty:claimed"}, {"name": "bounty:delivered"}],
                 "user": {"login": "FuRongJun-1999"}},
            ]
        def comments(self, n):
            return ['<!-- bounty:v1 {"state":"delivered","holder":"alice","seq":2} -->'] if n == 42 else [
                '<!-- bounty:v1 {"state":"claimed","holder":"alice","seq":1} -->'
            ]

    dlc = _DualLabelClient()
    ok("W6a", "count_active_claims 对同时带 claimed+delivered 的 issue 去重不重复计数（#2438）",
       dlc.count_active_claims("alice") == 2 and dlc.count_active_claims("alice", exclude=43) == 1,
       (dlc.count_active_claims("alice"), dlc.count_active_claims("alice", exclude=43)))

    return red, total[0]


MUTANTS = (
    ("WM1", "apply_live 丢弃 extra_events",
     "        if dec.extra_events:\n            events.extend(dec.extra_events)",
     "        if False:\n            events.extend(dec.extra_events)  # MUT",
     {"W1a", "W1b"}),
    ("WM2", "extract_pr_number 取消 host==github.com 校验",
     'or (parsed.hostname or "").lower() != "github.com"',
     'or False  # MUT',
     {"W2b"}),
    ("WM3", "handle_issue_comment /bid 不取 pr_meta",
     '    if cmd in ("/deliver", "/bid"):',
     '    if cmd == "/deliver":  # MUT',
     {"W3a"}),
    ("WM4", "rescore 去掉非对象 formula 守卫",
     "        if not isinstance(f, dict):",
     "        if False:  # MUT",
     {"W4a"}),
    ("WM5", "rescore 去掉负 round 守卫",
     "                if _rnd < 0:",
     "                if False:  # MUT",
     {"W4e"}),
    ("WM6", "rescore 去掉 bool delta 守卫",
     "        if (d != _got or isinstance(raw_delta, bool)",
     "        if (d != _got or False  # MUT",
     {"W4d"}),
    ("WM7", "append_events 不更新 seen（批内重复入账）",
     "            seen.add(eid)",
     "            pass  # MUT",
     {"W5a"}),
    ("WM8", "count_active_claims 不按 issue 号去重",
     "                if num in seen_issues:",
     "                if False:  # MUT",
     {"W6a"}),
)


def run_mutations() -> int:
    src = io.open(BB_PATH, encoding="utf-8").read().replace("\r\n", "\n")
    print(f"定点变异自证（test_bounty_board_wave4_guards）：{len(MUTANTS)} 条")
    failed = 0
    with tempfile.TemporaryDirectory(prefix="bb_w4_mut_") as td:
        for mid, desc, old, new, want in MUTANTS:
            cnt = src.count(old)
            if cnt != 1:
                print(f"  [ANCHOR-MISS] {mid} {desc} (hits={cnt})")
                return 2
            mp = os.path.join(td, f"bb_{mid}.py")
            with io.open(mp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(src.replace(old, new, 1))
            mod = _load_bb(mp, f"bb_mut_{mid}")
            try:
                red, _tot = run_suite(mod, quiet=True)
                got = set(red)
            except Exception as exc:  # noqa: BLE001
                got = {f"CRASH:{type(exc).__name__}"}
            # For WM4 (removing non-dict formula guard), W4a crashes inside rescore
            hit = (got == want)
            print(f"  [{'PASS' if hit else 'FAIL'}] {mid} {desc} -> got={sorted(got)} want={sorted(want)}")
            if not hit:
                failed += 1
    print(f"变异守卫：{len(MUTANTS)} 条 · 通过 {len(MUTANTS) - failed} · 失败 {failed}")
    return 1 if failed else 0


def main() -> int:
    if "--mutate" in sys.argv:
        return run_mutations()
    print("守卫 · bounty_board wave4（apply_live / extract_pr_number / /bid / rescore / append_events / count_active_claims）")
    bb = _load_bb(BB_PATH, "bb_wave4_real")
    red, tot = run_suite(bb, quiet=False)
    print(f"通过 {tot - len(red)} / 失败 {len(red)}")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
