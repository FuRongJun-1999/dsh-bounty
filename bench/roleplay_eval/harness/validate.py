#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验适配器输出是否符合 CONTRACT §3.2。

用法：python -X utf8 harness/validate.py out/baseline_P0.json [--data data] [--strict-content]

逐项打印 OK <check-id> / FAIL <check-id> <细节>，末行 SUMMARY；有 FAIL 即退出码 1。
每个 check-id 固定，报错时点名是哪一处不一致。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import metrics  # noqa: E402

TOP_KEYS = {"adapter", "upstream_repo", "upstream_commit", "adapter_version", "engine_env",
            "capabilities", "turns", "unsupported", "errors"}
TURN_KEYS = {"turn", "profile", "history_len", "active_uids", "inject_order", "blocks",
             "totals", "engine_notes"}
BLOCK_KEYS = {"uid", "position", "depth", "chars", "bytes", "sha256"}
TOTALS_KEYS = {"active", "chars", "bytes", "dropped_uids"}
CAP_KEYS = {"recursive", "group", "probability", "regex_key", "at_depth", "whole_words_cjk"}
POSITIONS = {"before_char", "after_char", "at_depth"}
PROFILES = {"P0", "P1", "P2", "P3", "P4"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
NO_SPACE = re.compile(r"^\S+$")

STATE = {"checks": 0, "fail": 0, "notes": []}


def ok(cid, detail=""):
    STATE["checks"] += 1
    print("OK %s %s" % (cid, detail))


def fail(cid, detail):
    STATE["checks"] += 1
    STATE["fail"] += 1
    print("FAIL %s %s" % (cid, detail))


def note(text):
    STATE["notes"].append(text)
    print("NOTE %s" % text)


def check_types(doc):
    bad = []
    for key in ("adapter", "upstream_repo", "adapter_version"):
        if not isinstance(doc.get(key), str):
            bad.append("%s:not-string" % key)
    uc = doc.get("upstream_commit")
    if not (uc is None or (isinstance(uc, str) and HEX40.match(uc))):
        bad.append("upstream_commit:not-null-and-not-40hex")
    if not isinstance(doc.get("turns"), list):
        bad.append("turns:not-list")
    if not isinstance(doc.get("unsupported"), list):
        bad.append("unsupported:not-list")
    if not isinstance(doc.get("errors"), list):
        bad.append("errors:not-list")
    env = doc.get("engine_env")
    if not isinstance(env, dict) or not env or not all(
            isinstance(k, str) and isinstance(v, str) and v for k, v in env.items()):
        bad.append("engine_env:not-nonempty-string-map")
    if bad:
        fail("C02-types", ",".join(bad))
    else:
        ok("C02-types", "upstream_commit=%s" % ("null" if uc is None else uc[:8] + "..."))


def check_caps(doc):
    caps = doc.get("capabilities")
    if not isinstance(caps, dict):
        fail("C03-capabilities", "capabilities:not-object")
        return
    missing = sorted(CAP_KEYS - set(caps))
    extra = sorted(set(caps) - CAP_KEYS)
    bad = []
    for k, v in sorted(caps.items()):
        if isinstance(v, bool) or (isinstance(v, str) and v):
            continue
        bad.append("%s:bad-type" % k)
    if missing or extra or bad:
        fail("C03-capabilities", "missing=%s extra=%s %s"
             % (metrics.fmt_uids([]) if not missing else ",".join(missing),
                "-" if not extra else ",".join(extra), ",".join(bad)))
    else:
        ok("C03-capabilities", "keys=%d" % len(caps))


def fixture_content(data_dir):
    wb = json.loads((Path(data_dir) / "worldbook.json").read_text(encoding="utf-8"))
    return {e["uid"]: e["content"] for e in wb["entries"]}


def check_turn(t, tindex, uids, contents, strict):
    tag = "t%d" % tindex
    if not isinstance(t, dict) or set(t) != TURN_KEYS:
        fail("C04-turn-keys", "%s keys=%s" % (tag, sorted(t) if isinstance(t, dict) else type(t).__name__))
        return
    ok("C04-turn-keys", "%s" % tag)

    tn = t["turn"]
    if tn not in range(1, 7):
        fail("C05-turn-id", "%s turn=%r" % (tag, tn))
    elif t["profile"] not in PROFILES:
        fail("C05-turn-id", "%s profile=%r" % (tag, t["profile"]))
    elif t["history_len"] != 2 * tn:
        fail("C05-turn-id", "%s history_len=%r 应为 %d" % (tag, t["history_len"], 2 * tn))
    else:
        ok("C05-turn-id", "turn=%d profile=%s history_len=%d" % (tn, t["profile"], t["history_len"]))

    act = t["active_uids"]
    order = t["inject_order"]
    off_fixture = sorted({u for u in act if u not in uids})
    if not isinstance(act, list) or not all(isinstance(u, int) for u in act):
        fail("C06-active-shape", "%s active_uids 非整数列表" % tag)
    elif off_fixture:
        fail("C06-active-shape", "%s active_uids 越出夹具 uid: %s" % (tag, off_fixture))
    elif act != sorted(set(act)):
        fail("C06-active-shape", "%s active_uids 未升序去重: %s" % (tag, act))
    else:
        ok("C06-active-shape", "%s active=%d" % (tag, len(act)))

    # 主判据：active_uids 与 inject_order 必须同集合、同一批 uid。
    if not isinstance(order, list) or not all(isinstance(u, int) for u in order):
        fail("C07-order-consistency", "%s inject_order 非整数列表" % tag)
    elif len(order) != len(set(order)):
        fail("C07-order-consistency", "%s inject_order 有重复 uid: %s" % (tag, order))
    elif set(order) != set(act):
        fail("C07-order-consistency",
             "%s inject_order 与 active_uids 不一致 only_order=%s only_active=%s"
             % (tag, sorted(set(order) - set(act)), sorted(set(act) - set(order))))
    else:
        ok("C07-order-consistency", "%s order=%s" % (tag, metrics.join_uids(order)))

    blocks = t["blocks"]
    if not isinstance(blocks, list):
        fail("C08-blocks-shape", "%s blocks 非列表" % tag)
        return
    bad_keys = [b.get("uid") for b in blocks if not isinstance(b, dict) or set(b) != BLOCK_KEYS]
    if bad_keys:
        fail("C08-blocks-shape", "%s 块键集不合 §3.2: %s" % (tag, bad_keys))
    elif [b["uid"] for b in blocks] != order:
        fail("C08-blocks-shape", "%s 块序列 %s 与 inject_order %s 不符"
             % (tag, [b["uid"] for b in blocks], order))
    else:
        ok("C08-blocks-shape", "%s blocks=%d" % (tag, len(blocks)))

    seen = {}
    problems = []
    for b in blocks:
        u = b["uid"]
        if b["position"] not in POSITIONS:
            problems.append("uid%d:position=%r" % (u, b["position"]))
        if not (b["depth"] is None or (isinstance(b["depth"], int) and b["depth"] >= 1)):
            problems.append("uid%d:depth=%r" % (u, b["depth"]))
        if not HEX64.match(str(b["sha256"])):
            problems.append("uid%d:sha256=%r" % (u, b["sha256"]))
        if not isinstance(b["chars"], int) or not isinstance(b["bytes"], int):
            problems.append("uid%d:chars/bytes 非整数" % u)
        elif b["chars"] < 0 or b["bytes"] < 0:
            problems.append("uid%d:chars/bytes 为负" % u)
        elif b["chars"] == 0 and not (b["bytes"] == 0 and b["sha256"] == metrics.sha256_text("")):
            problems.append("uid%d:空正文的自洽失败" % u)
        elif b["chars"] > 0 and b["bytes"] < b["chars"]:
            problems.append("uid%d:bytes<char s" % u)
        if u in seen and seen[u] != (b["chars"], b["bytes"], b["sha256"]):
            problems.append("uid%d:同 uid 块读数不一致" % u)
        seen[u] = (b["chars"], b["bytes"], b["sha256"])
    if problems:
        fail("C09-block-fields", "%s %s" % (tag, ";".join(problems[:6])))
    else:
        ok("C09-block-fields", "%s sha/尺寸格式与自洽通过" % tag)

    # 与夹具正文对表：digest 相同才算 verified。默认只记 NOTE，--strict-content 才判红。
    unverified = []
    for b in blocks:
        c = contents.get(b["uid"])
        if c is None:
            unverified.append(b["uid"])
            continue
        if (metrics.chars(c), metrics.bytes_of(c), metrics.sha256_text(c)) != \
                (b["chars"], b["bytes"], b["sha256"]):
            unverified.append(b["uid"])
    if unverified and strict:
        fail("C10-block-content", "%s 与夹具正文不符: %s" % (tag, unverified))
    elif unverified:
        note("C10-block-content %s 未与夹具正文逐字对上: %s" % (tag, unverified))
    else:
        ok("C10-block-content", "%s 全部块与夹具正文一致" % tag)

    tot = t["totals"]
    if not isinstance(tot, dict) or set(tot) != TOTALS_KEYS:
        fail("C11-totals", "%s totals 键集不符: %s" % (tag, sorted(tot) if isinstance(tot, dict) else tot))
        return
    exp_c = sum(b["chars"] for b in blocks)
    exp_b = sum(b["bytes"] for b in blocks)
    bad = []
    if tot["active"] != len(act):
        bad.append("active=%r 应为 %d" % (tot["active"], len(act)))
    if tot["chars"] != exp_c:
        bad.append("chars=%r 应为 %d" % (tot["chars"], exp_c))
    if tot["bytes"] != exp_b:
        bad.append("bytes=%r 应为 %d" % (tot["bytes"], exp_b))
    if bad:
        fail("C11-totals", "%s %s" % (tag, ";".join(bad)))
    else:
        ok("C11-totals", "%s chars=%d bytes=%d" % (tag, exp_c, exp_b))

    dr = tot["dropped_uids"]
    bad = []
    if not isinstance(dr, list) or not all(isinstance(u, int) for u in dr):
        bad.append("非整数列表")
    elif dr != sorted(set(dr)):
        bad.append("未升序去重: %s" % dr)
    elif [u for u in dr if u not in uids]:
        bad.append("越出夹具 uid")
    elif set(dr) & set(act):
        bad.append("与 active_uids 重叠: %s" % sorted(set(dr) & set(act)))
    if bad:
        fail("C12-dropped", "%s %s" % (tag, ";".join(bad)))
    else:
        ok("C12-dropped", "%s dropped=%s" % (tag, metrics.fmt_uids(dr)))


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="校验适配器输出（CONTRACT §3.2）")
    ap.add_argument("path")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--strict-content", action="store_true")
    args = ap.parse_args(argv)

    try:
        raw = Path(args.path).read_text(encoding="utf-8")
        doc = json.loads(raw)
    except Exception as exc:
        fail("C01-json", "%s 读取/解析失败: %s" % (args.path, exc))
        print("SUMMARY file=%s checks=%d fail=%d" % (args.path, STATE["checks"], STATE["fail"]))
        return 1
    ok("C01-json", "%s bytes=%d" % (args.path, len(raw.encode("utf-8"))))

    if not isinstance(doc, dict) or set(doc) != TOP_KEYS:
        fail("C02-types", "顶层键集不符: %s" % (sorted(doc) if isinstance(doc, dict) else type(doc).__name__))
        print("SUMMARY file=%s checks=%d fail=%d" % (args.path, STATE["checks"], STATE["fail"]))
        return 1
    ok("C02-types", "顶层键集等于 §3.2")

    check_caps(doc)
    contents = fixture_content(args.data)
    uids = set(contents)

    turns = doc["turns"]
    if not isinstance(turns, list) or not turns:
        fail("C04-turn-keys", "turns 为空")
    else:
        ids = [t.get("turn") for t in turns if isinstance(t, dict)]
        if len(ids) != len(set(ids)):
            fail("C05-turn-id", "turn 重复: %s" % ids)
        else:
            ok("C05-turn-id", "turns=%d" % len(turns))
        for i, t in enumerate(turns):
            check_turn(t, i, uids, contents, args.strict_content)

    bad = []
    for i, u in enumerate(doc["unsupported"]):
        if not isinstance(u, dict) or set(u) != {"field", "reason"}:
            bad.append("unsupported[%d]:键集" % i)
        elif not u["field"] or not NO_SPACE.match(str(u["reason"])):
            bad.append("unsupported[%d]:reason 含空格或为空" % i)
    if bad:
        fail("C13-unsupported", ";".join(bad))
    else:
        ok("C13-unsupported", "n=%d" % len(doc["unsupported"]))

    bad = []
    for i, e in enumerate(doc["errors"]):
        if not isinstance(e, dict) or not isinstance(e.get("kind"), str):
            bad.append("errors[%d]:缺 kind" % i)
    if bad:
        fail("C14-errors", ";".join(bad))
    else:
        ok("C14-errors", "n=%d" % len(doc["errors"]))

    print("SUMMARY file=%s checks=%d fail=%d" % (args.path, STATE["checks"], STATE["fail"]))
    return 1 if STATE["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
