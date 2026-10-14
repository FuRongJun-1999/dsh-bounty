#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diceframe 适配器：用 diceframe 真实代码产出 CONTRACT 3.2 的输出契约。

CLI（3.3）：
  <venv python> -X utf8 adapters/diceframe/run.py --data <data 目录> --profile P0 \
      --out <out 文件> [--upstream <diceframe 源码根>]

只调用 diceframe 自己的模块：
  - src.lorebook.importer.draft_lorebook_import / write_import_entries：
    规范世界书 → 引擎条目（走 src/lorebook/adapters/sillytavern.py 的 ST 映射，
    canonical id 由引擎的 import_entry_id 生成）
  - src.lorebook.matcher.KeywordMatcher.build / match_with_recursive：激活
  - src.lorebook.retrieval.LoreRetriever._apply_budgets：per-book 预算 → merge → 整体预算与最终顺序
  - src.lorebook.activation.evaluate_probability（经 matcher）：概率门，rng 由本适配器按 seed 注入

适配器自己做的只有三件：档位到引擎字段的注入、消息窗口文本的构造、读数序列化。
每个映射选择与缺口见同目录 README.md。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # bench/roleplay_eval
# upstream/ 是只读快照，导入引擎源码不得在快照里落 __pycache__。
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "harness"))

import metrics  # noqa: E402  统一量尺与 7.2 读数行构造

ADAPTER = "diceframe"
UPSTREAM_REPO = "https://github.com/diceframe/diceframe"
UPSTREAM_COMMIT = "d2246e0d0d32867e8e090c238b588441bad96a28"
ENTRY = "bench/roleplay_eval/adapters/diceframe/run.py"
BOOK_ID = "book:roleplay-eval-worldbook"
DEFAULT_UPSTREAM = HERE / "upstream"

CAPABILITIES = {
    "recursive": True,
    "group": True,
    "probability": True,
    "regex_key": True,
    "at_depth": False,
    "whole_words_cjk": "no_match_cjk",
}

# 字段级能力缺口；每条理由的引擎依据见 README.md 的映射表。
UNSUPPORTED = [
    {"field": "depth", "reason": "st-depth-in-engine-unmapped-fields"},
    {"field": "position", "reason": "st-position-anchor-no-canonical-prompt-slot"},
    {"field": "capability_probe", "reason": "fixture-marker-not-an-engine-field"},
    {"field": "macro_expand", "reason": "engine-src-has-no-macro-expander"},
]


class RecordingStore:
    """只记录引擎组装出来的条目 payload；不落盘、不建库。

    write_import_entries 只用到 get_entry 与 add_book_entry 两个方法，字段映射、
    match_mode 与 selective_logic 归一化、canonical id 生成全部由引擎自己完成。
    """

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def get_entry(self, entry_id: str):
        return None

    def add_book_entry(self, book_id: str, payload: dict):
        row = dict(payload)
        self.rows.append(row)
        return row.get("id")


def load_engine(upstream: Path) -> dict:
    if not (upstream / "src" / "lorebook" / "matcher.py").is_file():
        print(metrics.error_line(ADAPTER, "-", "upstream-missing"))
        raise SystemExit("ERROR %s profile=- kind=upstream-missing" % ADAPTER)
    sys.path.insert(0, str(upstream))
    try:
        from src.lorebook.importer import draft_lorebook_import, write_import_entries
        from src.lorebook.matcher import KeywordMatcher
        from src.lorebook.retrieval import LoreRetriever
        from src.version import __version__
    except Exception as exc:                    # 依赖缺失或源码不匹配
        print(metrics.error_line(ADAPTER, "-", "engine-import-failed"))
        raise SystemExit("ERROR %s profile=- kind=engine-import-failed (%s)" % (ADAPTER, exc))
    return {
        "draft_lorebook_import": draft_lorebook_import,
        "write_import_entries": write_import_entries,
        "KeywordMatcher": KeywordMatcher,
        "LoreRetriever": LoreRetriever,
        "version": str(__version__),
    }


def st_rows(entries: list[dict], prof: dict) -> list[dict]:
    """规范世界书条目 → SillyTavern 形状载荷（引擎自带 ST 适配器的输入词汇）。

    只改字段名，不改语义。档位级 case_sensitive / whole_words 在这里注入条目级开关，
    因为引擎的匹配口径只有条目级字段（见 README 映射表）。
    """
    rows = []
    for e in entries:
        rows.append({
            "uid": int(e["uid"]),
            "comment": e["comment"],
            "content": e["content"],
            "keys": list(e["keys"]),
            "secondary_keys": list(e["secondary_keys"]),
            "disable": not bool(e["enabled"]),
            "constant": bool(e["constant"]),
            "selective": bool(e["selective"]),
            "selective_logic": e["selective_logic"],
            "order": int(e["order"]),
            "probability": int(e["probability"]),
            "group": e["group"] or "",
            "groupWeight": int(e["group_weight"]),
            "caseSensitive": bool(prof["case_sensitive"]) or bool(e["case_sensitive"]),
            "matchWholeWords": bool(prof["whole_words"]) or bool(e["match_whole_words"]),
            "position": e["position"],
            "depth": e["depth"] if e["depth"] is not None else "",
            "excludeRecursion": bool(e["recursion"]["exclude"]),
            "preventRecursion": bool(e["recursion"]["prevent"]),
            "delayUntilRecursion": bool(e["recursion"]["delay"]),
        })
    return rows


def build_engine_rows(engine: dict, entries: list[dict], prof: dict):
    """规范条目 → 引擎 matcher 直接消费的行（注解口径同 retrieval.py:455-470）。"""
    draft = engine["draft_lorebook_import"]({"name": "roleplay-eval-worldbook",
                                              "entries": st_rows(entries, prof)})
    store = RecordingStore()
    written = engine["write_import_entries"](store, draft, BOOK_ID, None)
    if len(written) != len(entries) or len(store.rows) != len(entries):
        raise SystemExit("ERROR %s profile=%s kind=entry-count-mismatch" % (ADAPTER, prof["name"]))
    rows = []
    id_to_uid = {}
    for row, e in zip(store.rows, entries):
        row = dict(row)
        row["_lorebook_id"] = BOOK_ID
        row["_lorebook_order"] = 0
        row["_lorebook_token_budget"] = 0
        row["_lorebook_scan_depth"] = int(prof["scan_depth"])
        # 档位 recursive → 引擎的 book 级 recursive_scanning（retrieval.py:463-464 → matcher.py:453）
        row["_lorebook_recursive_scanning"] = bool(prof["recursive"])
        # 引擎对 ST 导入书（source_kind=device）的 fuzzy 默认是关（resolver.py:56-60）
        row["_lorebook_fuzzy_enabled"] = False
        row["_lorebook_vector_activation"] = "hybrid"
        rows.append(row)
        id_to_uid[str(row["id"])] = int(e["uid"])
    return draft, rows, id_to_uid


def window_text(chat: list[dict], depth: int) -> str:
    """2 规则 1：最近 depth 条消息。窗口文本是调用方职责（引擎只接收一段文本）。"""
    d = max(0, int(depth))
    window = chat[len(chat) - d:] if d else []
    return "\n".join(m["text"] for m in window)


def run_turn(engine: dict, rows: list[dict], id_to_uid: dict, by_uid: dict,
             chat: list[dict], prof: dict, turn: int) -> dict:
    hist = chat[: 2 * turn]
    depth = int(prof["scan_depth"])
    text = window_text(hist, depth)
    rnd = random.Random(int(prof["seed"]))
    matcher = engine["KeywordMatcher"](rng=rnd.random)
    matcher.build(rows)
    activated = matcher.match_with_recursive(
        text,
        timed_state=None,
        is_visible=None,
        is_candidate=None,
        extra_candidates=None,
        current_tick=None,
        max_activated=None,
    )
    selected, omitted = engine["LoreRetriever"]._apply_budgets(
        activated, int(prof["budget_chars"]))

    reasons: dict[str, int] = {}
    for row in (matcher.last_decisions or {}).values():
        if str(row.get("outcome") or "") != "rejected":
            continue
        code = str(row.get("reason_code") or "")
        if code:
            reasons[code] = reasons.get(code, 0) + 1
    notes = [
        "window=%d" % depth,
        "history=%d" % len(hist),
        "budget_chars=%d" % int(prof["budget_chars"]),
        "seed=%d" % int(prof["seed"]),
        "reject=" + (",".join("%s:%d" % kv for kv in sorted(reasons.items())) or "-"),
    ]
    if matcher.last_cutoff:
        notes.append("cutoff=%s" % matcher.last_cutoff)

    blocks = []
    tot_c = tot_b = 0
    for row in selected:
        uid = id_to_uid[str(row["id"])]
        e = by_uid[uid]
        c = metrics.chars(e["content"])
        b = metrics.bytes_of(e["content"])
        tot_c += c
        tot_b += b
        blocks.append({
            "uid": uid,
            "position": e["position"],
            "depth": e["depth"],
            "chars": c,
            "bytes": b,
            "sha256": metrics.sha256_text(e["content"]),
        })
    order = [blk["uid"] for blk in blocks]
    dropped = sorted({id_to_uid[str(o)] for o in omitted if str(o) in id_to_uid})
    return {
        "turn": turn,
        "profile": prof["name"],
        "history_len": len(hist),
        "active_uids": sorted(order),
        "inject_order": order,
        "blocks": blocks,
        "totals": {"active": len(order), "chars": tot_c, "bytes": tot_b,
                   "dropped_uids": dropped},
        "engine_notes": sorted(notes),
    }


def build(data_dir: Path, profile_name: str, upstream: Path):
    entries = json.loads((data_dir / "worldbook.json").read_text(encoding="utf-8"))["entries"]
    for e in entries:
        if e["position"] not in ("before_char", "after_char", "at_depth"):
            raise SystemExit("ERROR %s profile=%s kind=unknown-position-%s"
                             % (ADAPTER, profile_name, e["position"]))
    chat = [json.loads(line) for line in
            (data_dir / "chat.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    profs = json.loads((data_dir / "profiles.json").read_text(encoding="utf-8"))
    prof = next((p for p in profs["profiles"] if p["name"] == profile_name), None)
    if prof is None:
        print(metrics.error_line(ADAPTER, profile_name, "unknown-profile"))
        raise SystemExit("ERROR %s profile=%s kind=unknown-profile" % (ADAPTER, profile_name))

    engine = load_engine(upstream)
    draft, rows, id_to_uid = build_engine_rows(engine, entries, prof)
    by_uid = {int(e["uid"]): e for e in entries}
    turns = [run_turn(engine, rows, id_to_uid, by_uid, chat, prof, k) for k in range(1, 7)]
    try:
        upstream_label = upstream.resolve().relative_to(ROOT.parent.parent).as_posix()
    except ValueError:
        upstream_label = str(upstream.resolve())
    doc = {
        "adapter": ADAPTER,
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "adapter_version": engine["version"],
        "engine_env": {
            "python": sys.version.split()[0],
            "entry": ENTRY,
            "upstream": upstream_label,
            "llm": "none",
            "network": "none",
        },
        "capabilities": CAPABILITIES,
        "turns": turns,
        "unsupported": UNSUPPORTED,
        "errors": [],
    }
    return doc, list(draft.warnings)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="diceframe 适配器（CONTRACT 3.2）")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--profile", default="P0")
    ap.add_argument("--out", default=None)
    ap.add_argument("--upstream", default=os.environ.get("DICEFRAME_UPSTREAM", str(DEFAULT_UPSTREAM)))
    args = ap.parse_args(argv)

    doc, book_notes = build(Path(args.data), args.profile, Path(args.upstream))

    print(metrics.caps_line(ADAPTER, doc["capabilities"]))
    for t in doc["turns"]:
        print(metrics.readout_line(ADAPTER, args.profile, t["turn"], t["active_uids"],
                                   t["inject_order"], t["totals"]["chars"],
                                   t["totals"]["bytes"], t["totals"]["dropped_uids"]))
    for u in doc["unsupported"]:
        print(metrics.unsupported_line(ADAPTER, u["field"], u["reason"]))
    for w in book_notes:
        print("ENGINE_NOTE %s warning=%s" % (ADAPTER, " ".join(str(w).split())))
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
