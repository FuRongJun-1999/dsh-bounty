#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手写基线适配器：按 CONTRACT §2 的十条语义规范实现。

CLI（§3.3）：
  python -X utf8 adapters/baseline/run.py --data <data 目录> --profile P0 --out <out 文件>

输出：stdout 逐 turn 的 READOUT 行 ＋ CAPS/UNSUPPORTED 行 ＋ 一行完整契约 JSON；
      --out 指定的 §3.2 契约 JSON。只读 data/，只写 --out。

实现口径（契约未写死、由本文件固定并公开）：
  - 空主键 ⇒ 主键不命中（空集 any 为假）；uid23 因此永不激活。
  - 次级键一律在「该条目自己的窗口文本」里判，递归轮次也如此。
  - 全词匹配用 \b 语义，仅当键首尾都是 word 字符时启用；否则退回普通包含。
  - 概率条目每 turn 重置 random.Random(20261014)，按 uid 升序取一次 randint(1,100)。
  - 递归轮的额外文本＝当前已激活条目的正文；constant 条目由规则 4 直接入候选，不参与递归触发。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent.parent          # bench/roleplay_eval
sys.path.insert(0, str(ROOT / "harness"))

import metrics  # noqa: E402  统一量尺与 §7.2 行构造

ADAPTER = "baseline"
UPSTREAM_REPO = "local://bench/roleplay_eval/adapters/baseline"
ADAPTER_VERSION = "baseline-v1"
ENTRY = "bench/roleplay_eval/adapters/baseline/run.py"
CAPABILITIES = {
    "recursive": True,
    "group": True,
    "probability": True,
    "regex_key": False,
    "at_depth": True,
    "whole_words_cjk": "no_match_cjk",
}
UNSUPPORTED = [
    {"field": "regex_key", "reason": "baseline-literal-key"},
    {"field": "macro_expand", "reason": "baseline-no-macro"},
    {"field": "tokenizer", "reason": "baseline-no-tokenizer"},
    {"field": "upstream_commit", "reason": "baseline-local-no-upstream"},
]


def _word_char(ch):
    return ch.isalnum() or ch == "_"


def key_hit(text, key, case_sensitive, whole_words):
    """规则 2：主键命中。全词＝\b 语义；大小写不敏感＝Unicode 折叠。"""
    if not key:
        return False
    flags = 0 if case_sensitive else re.IGNORECASE
    if whole_words and _word_char(key[0]) and _word_char(key[-1]):
        return re.search(r"\b" + re.escape(key) + r"\b", text, flags) is not None
    if case_sensitive:
        return key in text
    return key.lower() in text.lower()


def window_of(hist, depth):
    """规则 1：最近 depth 条消息。depth 为 0 时窗口为空。"""
    d = max(0, int(depth))
    return hist[len(hist) - d:] if d else []


def text_of(msgs):
    return "\n".join(m["text"] for m in msgs)


def fit(e, prof):
    """匹配口径：档位与条目取或；条目 true 表示强制该口径。"""
    return (bool(prof["case_sensitive"]) or bool(e["case_sensitive"]),
            bool(prof["whole_words"]) or bool(e["match_whole_words"]))


def depth_of(e, prof):
    return int(e["depth"]) if e["depth"] is not None else int(prof["scan_depth"])


def secondary_ok(e, text, cs, ww):
    """规则 3：and_any / and_all / not_any。空次级键：and_all 为假，not_any 为真。"""
    hits = [key_hit(text, k, cs, ww) for k in e["secondary_keys"]]
    logic = e["selective_logic"]
    if logic == "and_any":
        return any(hits)
    if logic == "and_all":
        return bool(hits) and all(hits)
    if logic == "not_any":
        return not any(hits)
    raise ValueError("未知 selective_logic: %s" % logic)


def direct_candidates(entries, hist, prof):
    """规则 1/2/3/4/5：直接候选。"""
    out = []
    for e in entries:
        if not e["enabled"]:
            continue
        if e["constant"]:
            out.append(e)
            continue
        if not e["keys"]:
            continue
        cs, ww = fit(e, prof)
        text = text_of(window_of(hist, depth_of(e, prof)))
        if not any(key_hit(text, k, cs, ww) for k in e["keys"]):
            continue
        if e["selective"] and not secondary_ok(e, text, cs, ww):
            continue
        out.append(e)
    return out


def recursive_candidates(entries, hist, prof, active):
    """规则 6：已激活正文作为额外扫描文本，最多 recursive_max_depth 层。"""
    added = []
    pool = list(active)
    for _layer in range(1, int(prof["recursive_max_depth"]) + 1):
        extra = "\n".join(e["content"] for e in sorted(pool, key=lambda x: x["uid"]))
        have = {e["uid"] for e in pool}
        new = []
        for e in entries:
            if e["uid"] in have or not e["enabled"]:
                continue
            if e["recursion"]["exclude"] or e["constant"]:
                continue
            cs, ww = fit(e, prof)
            win_text = text_of(window_of(hist, depth_of(e, prof)))
            if not any(key_hit(win_text + "\n" + extra, k, cs, ww) for k in e["keys"]):
                continue
            if e["selective"] and not secondary_ok(e, win_text, cs, ww):
                continue
            new.append(e)
        if not new:
            break
        pool = pool + new
        added = added + new
    return pool, added


def apply_group(cands):
    """规则 7：同组取 weight 最大，同权取 uid 小。返回 (保留, 落选 uid)。"""
    keep = {e["uid"]: e for e in cands}
    groups = {}
    for e in cands:
        if e["group"]:
            groups.setdefault(e["group"], []).append(e)
    losers = []
    for _g, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        winner = sorted(members, key=lambda e: (-int(e["group_weight"]), e["uid"]))[0]
        for m in members:
            if m["uid"] != winner["uid"]:
                keep.pop(m["uid"], None)
                losers.append(m["uid"])
    return [keep[u] for u in sorted(keep)], sorted(losers)


def apply_probability(cands, seed):
    """规则 8：probability<100 的条目过随机判定；每 turn 重置种子，按 uid 升序取数。"""
    rng = random.Random(int(seed))
    kept, rejected = [], []
    for e in sorted(cands, key=lambda x: x["uid"]):
        p = int(e["probability"])
        if p >= 100:
            kept.append(e)
            continue
        roll = rng.randint(1, 100)
        if roll <= p:
            kept.append(e)
        else:
            rejected.append(e["uid"])
    return kept, rejected


def apply_budget(cands, budget):
    """规则 9/10：order 降序、uid 升序；预算不够的条目跳过并记为 dropped。"""
    ordered = sorted(cands, key=lambda e: (-int(e["order"]), e["uid"]))
    kept, dropped, used = [], [], 0
    for e in ordered:
        n = metrics.chars(e["content"])
        if used + n <= int(budget):
            kept.append(e)
            used += n
        else:
            dropped.append(e["uid"])
    return kept, sorted(dropped)


def run_turn(entries, chat, prof, turn):
    hist = chat[: 2 * turn]
    actives = direct_candidates(entries, hist, prof)
    notes = ["window=%d" % int(prof["scan_depth"]), "history=%d" % len(hist)]
    if prof["recursive"]:
        pool, added = recursive_candidates(entries, hist, prof, actives)
        if added:
            notes.append("recursive_added=" + metrics.fmt_uids([e["uid"] for e in added]))
        actives = pool
    actives, group_losers = apply_group(actives)
    if group_losers:
        notes.append("group_loser=" + metrics.fmt_uids(group_losers))
    actives, prob_reject = apply_probability(actives, prof["seed"])
    if prob_reject:
        notes.append("probability_reject=" + metrics.fmt_uids(prob_reject))
    kept, dropped = apply_budget(actives, prof["budget_chars"])
    if dropped:
        notes.append("budget_drop=" + metrics.fmt_uids(dropped))

    blocks = []
    tot_c = tot_b = 0
    for e in kept:
        c = metrics.chars(e["content"])
        b = metrics.bytes_of(e["content"])
        tot_c += c
        tot_b += b
        blocks.append({
            "uid": e["uid"],
            "position": e["position"],
            "depth": e["depth"],
            "chars": c,
            "bytes": b,
            "sha256": metrics.sha256_text(e["content"]),
        })
    return {
        "turn": turn,
        "profile": prof["name"],
        "history_len": len(hist),
        "active_uids": sorted(e["uid"] for e in kept),
        "inject_order": [e["uid"] for e in kept],
        "blocks": blocks,
        "totals": {"active": len(kept), "chars": tot_c, "bytes": tot_b,
                   "dropped_uids": sorted(dropped)},
        "engine_notes": sorted(notes),
    }


def build(data_dir, profile_name, out_path):
    wb = json.loads((Path(data_dir) / "worldbook.json").read_text(encoding="utf-8"))
    entries = wb["entries"]
    chat = [json.loads(line) for line in
            (Path(data_dir) / "chat.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    profs = json.loads((Path(data_dir) / "profiles.json").read_text(encoding="utf-8"))
    prof = None
    for p in profs["profiles"]:
        if p["name"] == profile_name:
            prof = p
    if prof is None:
        raise SystemExit("ERROR %s profile=%s kind=unknown-profile" % (ADAPTER, profile_name))
    turns = [run_turn(entries, chat, prof, k) for k in range(1, 7)]
    doc = {
        "adapter": ADAPTER,
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": None,
        "adapter_version": ADAPTER_VERSION,
        "engine_env": {
            "python": sys.version.split()[0],
            "entry": ENTRY,
            "stdlib_only": "true",
            "network": "none",
        },
        "capabilities": CAPABILITIES,
        "turns": turns,
        "unsupported": UNSUPPORTED,
        "errors": [],
    }
    return doc, out_path


def main(argv=None):
    global ADAPTER
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="手写基线适配器（CONTRACT §2）")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--profile", default="P0")
    ap.add_argument("--out", default=None)
    ap.add_argument("--name", default=ADAPTER, help="读数行里的适配器名")
    args = ap.parse_args(argv)
    ADAPTER = args.name

    doc, _ = build(args.data, args.profile, args.out)
    print(metrics.caps_line(ADAPTER, doc["capabilities"]))
    for t in doc["turns"]:
        print(metrics.readout_line(ADAPTER, args.profile, t["turn"], t["active_uids"],
                                   t["inject_order"], t["totals"]["chars"],
                                   t["totals"]["bytes"], t["totals"]["dropped_uids"]))
    for u in doc["unsupported"]:
        print(metrics.unsupported_line(ADAPTER, u["field"], u["reason"]))
    for e in doc["errors"]:
        print(metrics.error_line(ADAPTER, args.profile, e.get("kind", "unknown")))
    print("JSON %s %s %s" % (ADAPTER, args.profile,
                             json.dumps(doc, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":"))))
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                     encoding="utf-8", newline="\n")
    return 0 if not doc["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
