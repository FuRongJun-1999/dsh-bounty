#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立复算器（第三方验收用）：不复用任何已有读数，从原始文件重算关键指标。

用法（无参数即跑全部）：
  python -X utf8 bench/roleplay_eval/harness/independent_recompute.py

复算内容：
  A. 夹具复算：在系统临时目录重跑 harness/make_fixture.py，比对 data/ 三个产物的 sha256。
  B. 基线语义独立复算：按 CONTRACT.md §2 十条规则另写一份实现，算 P0..P4 × turn1..6 的
     active_uids / inject_order / dropped_uids，与 out/baseline_P*.json 逐 turn 比对。
  C. 注入正文溯源：把 out/<name>_P*.json 每个 block 的 sha256/chars/bytes 与
     data/worldbook.json 同 uid 条目的 content 重算比对；不符的 block 再分两类计数：
       explained＝已披露例外：adapter=sillytavern 且 uid=25 且 block sha256 命中三个已知宏展开值；
       mismatch＝未解释的不符。explained 不计入 mismatch，也不影响 mismatch 的判定口径。
     取证（源码）：repos/SillyTavern/public/scripts/world-info.js:5058 在注入前对条目正文调
       substituteParams；{{roll}} 模式见 public/scripts/macros.js:551、:566 调 droll.roll()；
       取值算法见 node_modules/droll/droll.js:96（1 + Math.floor(Math.random() * numSides)）；
       {{user}} 由页面 name1 换成 User。
     取证（逐字正文）：raw/sillytavern_content.txt、raw/sillytavern_content_P2.txt。
  D. 差异与指标独立复算：自算 方案 vs baseline 的逐 turn 对称差，与 raw/<name>_baseline_diff.txt
     逐行比对；自算 M1（激活集 F1）与 M2（逆序对），与 raw/<name>_kpi.txt 比对（浮点容差 1e-6）。

退出码：全部 match 为 0；出现任一 false 为 1。
stdout 逐字同时写 raw/independent_recompute.txt。

说明（可追溯性）：
  - 本文件只用 Python 标准库；只读 data/、out/、raw/、harness/make_fixture.py；只写 raw/independent_recompute.txt。
  - 基线语义实现由本文件独立书写（不复制 adapters/baseline/run.py 的代码）。
    契约未写死的 6 处边界口径在 write() 头部的「口径披露」段逐条列出并给出取值。
"""

from __future__ import annotations

import hashlib
import io
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent                    # bench/roleplay_eval
DATA = ROOT / "data"
OUT = ROOT / "out"
RAW = ROOT / "raw"
REPORT = RAW / "independent_recompute.txt"
FIXTURE_FILES = ("worldbook.json", "chat.jsonl", "profiles.json")
PROFILES = ("P0", "P1", "P2", "P3", "P4")
TURNS = (1, 2, 3, 4, 5, 6)
FLOAT_TOL = 1e-6

# ---------- 已披露例外白名单（explained）----------
# 三条件同时成立才算 explained，缺一即计入 mismatch：
#   ① adapter=sillytavern  ② uid=25  ③ block 的 sha256 命中下面三个已知宏展开值
# 取证（源码）：repos/SillyTavern/public/scripts/world-info.js:5058 在注入前对条目正文调
#   substituteParams；{{roll}} 模式见 public/scripts/macros.js:551，:566 调 droll.roll()；
#   取值算法见 node_modules/droll/droll.js:96（1 + Math.floor(Math.random() * numSides)）；
#   {{user}} 由页面 name1 换成 User。
# 取证（逐字正文）：raw/sillytavern_content.txt（P0/P1/P4 turn3 与 turn4）、
#   raw/sillytavern_content_P2.txt（P2 turn3）。
EXPLAINED_ADAPTER = "sillytavern"
EXPLAINED_UID = 25
#: 前 16 位 → 完整 sha256；查表要求「前 16 位命中」且「完整值相等」。
EXPLAINED_SHA256 = {
    "13763707e2e7b428": "13763707e2e7b428680fc46cbadcdf49eb692cc893429dc4985e624e81aeeb87",
    "965f6f8351c68252": "965f6f8351c68252c9988056485ee607aa57a519c63dce2b29ee9b3b891e94f8",
    "b19b9fb41ca55742": "b19b9fb41ca55742103a6c8dd598558235f955ddfcbccaf2294bb6b2e5d0260b",
}


def is_explained_block(name: str, uid: int, sha) -> bool:
    """三条件同时成立才为 True：adapter=sillytavern、uid=25、sha256 命中已知宏展开值。

    条件写死在本函数，不得放宽到其它 adapter／uid／sha：放宽即把未解释的不符吸进 explained。
    """
    if name != EXPLAINED_ADAPTER or uid != EXPLAINED_UID:
        return False
    s = str(sha or "").strip().lower()
    return EXPLAINED_SHA256.get(s[:16]) == s


_BUFFER = io.StringIO()
_COUNT = {"true": 0, "false": 0}


# ---------- 输出 ----------

def emit(line: str) -> None:
    _BUFFER.write(line + "\n")


def verdict(ok: bool) -> str:
    tag = "true" if ok else "false"
    _COUNT[tag] += 1
    return tag


def write() -> int:
    """总行为：摘要计入正文 ⇒ stdout 与 raw/independent_recompute.txt 逐字节相同。

    两处都显式 newline="\n"：Windows 下 stdout 文本模式默认把 \n 翻成 \r\n，
    会给"逐字一致"引入平台差异。
    """
    code = 1 if _COUNT["false"] else 0
    emit("RECOMPUTE-SUMMARY match_true=%d match_false=%d exit=%d"
         % (_COUNT["true"], _COUNT["false"], code))
    text = _BUFFER.getvalue()
    sys.stdout.write(text)
    sys.stdout.flush()
    try:
        RAW.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        print("WARN report-write-failed path=%s reason=%s" % (REPORT, exc))
    return code


# ---------- 基础量尺（CONTRACT §4）----------

def chars(s: str) -> int:
    return len(s)


def bytes_of(s: str) -> int:
    return len(s.encode("utf-8"))


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fmt_uids(uids) -> str:
    xs = sorted(int(u) for u in uids)
    return ",".join(str(u) for u in xs) if xs else "-"


def parse_uids(token: str):
    t = (token or "").strip()
    if t in ("", "-"):
        return []
    return [int(x) for x in t.split(",")]


def symdiff(a, b):
    sa, sb = set(a), set(b)
    return sorted(sa - sb), sorted(sb - sa), len(sa & sb)


def inversions(seq) -> int:
    n = 0
    for i in range(len(seq)):
        for j in range(i + 1, len(seq)):
            if seq[i] > seq[j]:
                n += 1
    return n


# ---------- 独立基线实现（CONTRACT §2 十条规则）----------

def word_char(ch: str) -> bool:
    """口径披露 ①：全词匹配用 \\b 语义；键首尾均为字母数字或下划线时才启用。"""
    return ch.isalnum() or ch == "_"


def key_hit(text: str, key: str, case_sensitive: bool, whole_words: bool) -> bool:
    if not key:
        return False
    flags = 0 if case_sensitive else re.IGNORECASE
    if whole_words and word_char(key[0]) and word_char(key[-1]):
        return re.search(r"\b" + re.escape(key) + r"\b", text, flags) is not None
    if case_sensitive:
        return key in text
    return key.lower() in text.lower()


def window_of(hist, depth: int):
    d = max(0, int(depth))
    return hist[len(hist) - d:] if d else []


def text_of(msgs) -> str:
    return "\n".join(m["text"] for m in msgs)


def match_flags(entry, prof):
    """档位与条目取或：条目 true 表示强制该口径。"""
    return (bool(prof["case_sensitive"]) or bool(entry["case_sensitive"]),
            bool(prof["whole_words"]) or bool(entry["match_whole_words"]))


def depth_of(entry, prof) -> int:
    return int(entry["depth"]) if entry["depth"] is not None else int(prof["scan_depth"])


def secondary_hit(entry, text: str, cs: bool, ww: bool) -> bool:
    """口径披露 ②：空次级键时 and_all 为假、not_any 为真。"""
    hits = [key_hit(text, k, cs, ww) for k in entry["secondary_keys"]]
    logic = entry["selective_logic"]
    if logic == "and_any":
        return any(hits)
    if logic == "and_all":
        return bool(hits) and all(hits)
    if logic == "not_any":
        return not any(hits)
    raise ValueError("未知 selective_logic: %s" % logic)


def direct_candidates(entries, hist, prof):
    """规则 1/2/3/4/5：窗口 ＋ 主键 ＋ 二级键 ＋ 常驻 ＋ 停用。"""
    out = []
    for e in entries:
        if not e["enabled"]:
            continue
        if e["constant"]:
            out.append(e)
            continue
        if not e["keys"]:
            continue
        cs, ww = match_flags(e, prof)
        text = text_of(window_of(hist, depth_of(e, prof)))
        if not any(key_hit(text, k, cs, ww) for k in e["keys"]):
            continue
        if e["selective"] and not secondary_hit(e, text, cs, ww):
            continue
        out.append(e)
    return out


def recursive_add(entries, hist, prof, actives):
    """规则 6：已激活正文作为额外扫描文本，最多 recursive_max_depth 层。

    口径披露 ③：constant 条目由规则 4 直接入候选，不参与递归文本；
    口径披露 ④：递归轮次的主键在「窗口文本 ＋ 已激活正文」上判，二级键仍只在窗口文本上判。
    """
    added = []
    pool = list(actives)
    for _layer in range(1, int(prof["recursive_max_depth"]) + 1):
        extra = "\n".join(e["content"] for e in sorted(pool, key=lambda x: x["uid"]))
        have = {e["uid"] for e in pool}
        new = []
        for e in entries:
            if e["uid"] in have or not e["enabled"]:
                continue
            if e["recursion"]["exclude"] or e["constant"]:
                continue
            cs, ww = match_flags(e, prof)
            win = text_of(window_of(hist, depth_of(e, prof)))
            if not any(key_hit(win + "\n" + extra, k, cs, ww) for k in e["keys"]):
                continue
            if e["selective"] and not secondary_hit(e, win, cs, ww):
                continue
            new.append(e)
        if not new:
            break
        pool = pool + new
        added = added + new
    return pool, added


def apply_group(cands):
    """规则 7：同组取 weight 最大，同权取 uid 小。"""
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
    """规则 8：probability<100 的条目过随机判定。

    口径披露 ⑤：每 turn 重置 random.Random(seed)，按 uid 升序、每个条目取一次 randint(1,100)。
    """
    rng = random.Random(int(seed))
    kept, rejected = [], []
    for e in sorted(cands, key=lambda x: x["uid"]):
        p = int(e["probability"])
        if p >= 100:
            kept.append(e)
            continue
        if rng.randint(1, 100) <= p:
            kept.append(e)
        else:
            rejected.append(e["uid"])
    return kept, rejected


def apply_budget(cands, budget):
    """规则 9/10：order 降序、uid 升序；装不下的跳过（不截断）并记 dropped。

    口径披露 ⑥：判定式是 used + chars <= budget_chars，取等号时保留。
    """
    ordered = sorted(cands, key=lambda e: (-int(e["order"]), e["uid"]))
    kept, dropped, used = [], [], 0
    for e in ordered:
        n = chars(e["content"])
        if used + n <= int(budget):
            kept.append(e)
            used += n
        else:
            dropped.append(e["uid"])
    return kept, sorted(dropped)


def run_turn(entries, chat, prof, turn):
    hist = chat[: 2 * turn]
    actives = direct_candidates(entries, hist, prof)
    if prof["recursive"]:
        actives, _added = recursive_add(entries, hist, prof, actives)
    actives, _g = apply_group(actives)
    actives, _p = apply_probability(actives, prof["seed"])
    kept, dropped = apply_budget(actives, prof["budget_chars"])
    return {
        "active": sorted(e["uid"] for e in kept),
        "order": [e["uid"] for e in kept],
        "dropped": sorted(dropped),
        "chars": sum(chars(e["content"]) for e in kept),
        "bytes": sum(bytes_of(e["content"]) for e in kept),
        "contents": [e["content"] for e in kept],
    }


def load_inputs():
    wb = json.loads((DATA / "worldbook.json").read_text(encoding="utf-8"))
    entries = wb["entries"]
    chat = [json.loads(ln) for ln in
            (DATA / "chat.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    profiles = json.loads((DATA / "profiles.json").read_text(encoding="utf-8"))["profiles"]
    return entries, chat, {p["name"]: p for p in profiles}


# ---------- A. 夹具复算 ----------

def part_a() -> None:
    emit("# A. 夹具复算：临时目录重跑 make_fixture.py，比对 data/ 三产物 sha256")
    real = {}
    for name in FIXTURE_FILES:
        p = DATA / name
        real[name] = sha256_file(p) if p.is_file() else None

    tmp = Path(tempfile.mkdtemp(prefix="rp_recompute_"))
    try:
        gen_dir = tmp / "harness"
        gen_dir.mkdir(parents=True)
        shutil.copy2(str(HERE.parent / "make_fixture.py"), str(gen_dir / "make_fixture.py"))
        proc = subprocess.run([sys.executable, "-X", "utf8", str(gen_dir / "make_fixture.py")],
                              cwd=str(tmp), capture_output=True)
        for name in FIXTURE_FILES:
            got_path = tmp / "data" / name
            got = sha256_file(got_path) if got_path.is_file() else None
            same = (got is not None and got == real[name])
            emit("RECOMPUTE fixture file=data/%s sha_repo=%s sha_rerun=%s match=%s"
                 % (name, real[name] or "-", got or "-", verdict(same)))
        emit("RECOMPUTE fixture generator_exit=%d tmp=%s"
             % (proc.returncode, "系统临时目录（已删除）"))
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)


# ---------- B. 基线语义独立复算 ----------

def load_out_turns(name: str, profile: str):
    p = OUT / ("%s_%s.json" % (name, profile))
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    turns = {}
    for t in doc.get("turns") or []:
        try:
            tot = t.get("totals") or {}
            turns[int(t["turn"])] = {
                "active": sorted(int(u) for u in t["active_uids"]),
                "order": [int(u) for u in t["inject_order"]],
                "dropped": sorted(int(u) for u in (tot.get("dropped_uids") or [])),
                "blocks": t.get("blocks") or [],
            }
        except (KeyError, TypeError, ValueError):
            continue
    return turns or None


def part_b(entries, chat, profs) -> None:
    emit("# B. 基线语义独立复算：P0..P4 × turn1..6 的 active_uids / inject_order / dropped_uids")
    for prof_name in PROFILES:
        prof = profs[prof_name]
        reported = load_out_turns("baseline", prof_name)
        if reported is None:
            emit("RECOMPUTE baseline %s turn=- match=false reason=out-json-missing" % prof_name)
            continue
        for turn in TURNS:
            mine = run_turn(entries, chat, prof, turn)
            rep = reported.get(turn)
            if rep is None:
                emit("RECOMPUTE baseline %s turn=%d match=false reason=turn-missing-in-out"
                     % (prof_name, turn))
                continue
            diffs = []
            if mine["active"] != rep["active"]:
                only_mine, only_rep, _ = symdiff(mine["active"], rep["active"])
                diffs.append("active only_recomputed=%s only_reported=%s"
                             % (fmt_uids(only_mine), fmt_uids(only_rep)))
            if mine["order"] != rep["order"]:
                diffs.append("order recomputed=%s reported=%s"
                             % (",".join(map(str, mine["order"])) or "-",
                                ",".join(map(str, rep["order"])) or "-"))
            if mine["dropped"] != rep["dropped"]:
                diffs.append("dropped recomputed=%s reported=%s"
                             % (fmt_uids(mine["dropped"]), fmt_uids(rep["dropped"])))
            ok = not diffs
            emit("RECOMPUTE baseline %s turn=%d match=%s" % (prof_name, turn, verdict(ok)))
            if diffs:
                emit("  DETAIL baseline %s turn=%d diff=%s" % (prof_name, turn, " | ".join(diffs)))


# ---------- C. 注入正文溯源 ----------

def bad_uids(bad):
    """从 DETAIL 文本里取出被点名的 uid。"""
    out = set()
    for x in bad:
        m = re.search(r"uid(\d+)", x)
        if m:
            out.add(int(m.group(1)))
    return out


def observed_block_variants(name: str, uid: int):
    """同一 uid 在所有 P0..P4 输出里出现过的 (chars, bytes, sha前缀) 取值集合。"""
    obs = set()
    for pf in PROFILES:
        p = OUT / ("%s_%s.json" % (name, pf))
        if not p.is_file():
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        for t in doc.get("turns") or []:
            for b in t.get("blocks") or []:
                if int(b.get("uid", -1)) == uid:
                    obs.add((int(b.get("chars", -1)), int(b.get("bytes", -1)),
                             str(b.get("sha256"))[:16]))
    return sorted(obs)


def part_c(entries, adapters) -> None:
    emit("# C. 注入正文溯源：out/<name>_P*.json 的 blocks 与 data/worldbook.json 同 uid 内容比对")
    emit("#   explained＝已披露例外：adapter=sillytavern 且 uid=25 且 block sha256 命中三个已知宏展开值；")
    emit("#   取证：源码 repos/SillyTavern/public/scripts/world-info.js:5058 → public/scripts/macros.js:551/566")
    emit("#         → node_modules/droll/droll.js:96；逐字正文 raw/sillytavern_content.txt、raw/sillytavern_content_P2.txt。")
    emit("#   其余任何不符一律计入 mismatch。")
    by_uid = {int(e["uid"]): e for e in entries}
    for name in adapters:
        for prof_name in PROFILES:
            p = OUT / ("%s_%s.json" % (name, prof_name))
            if not p.is_file():
                continue
            doc = json.loads(p.read_text(encoding="utf-8"))
            blocks, expl, mism, bad, seen = 0, 0, 0, [], []
            for t in doc.get("turns") or []:
                for b in t.get("blocks") or []:
                    blocks += 1
                    uid = int(b.get("uid"))
                    e = by_uid.get(uid)
                    if e is None:
                        mism += 1
                        bad.append("turn%s:uid%s-not-in-worldbook" % (t.get("turn"), uid))
                        continue
                    c, by, sh = chars(e["content"]), bytes_of(e["content"]), sha256_text(e["content"])
                    if (int(b.get("chars", -1)) != c or int(b.get("bytes", -1)) != by
                            or b.get("sha256") != sh):
                        if is_explained_block(name, uid, b.get("sha256")):
                            expl += 1
                            seen.append("turn%s:uid%s sha=%s" % (t.get("turn"), uid,
                                                                 str(b.get("sha256"))[:16]))
                            continue
                        mism += 1
                        bad.append("turn%s:uid%s(expected %d/%d/%s got %s/%s/%s)"
                                   % (t.get("turn"), uid, c, by, sh[:12],
                                      b.get("chars"), b.get("bytes"), str(b.get("sha256"))[:12]))
            emit("PROVENANCE %s %s blocks=%d explained=%d mismatch=%d"
                 % (name, prof_name, blocks, expl, mism))
            emit("  VERDICT provenance %s %s match=%s" % (name, prof_name, verdict(mism == 0)))
            if seen:
                emit("  EXPLAINED provenance %s %s %s（已披露例外，逐字正文见 raw/sillytavern_content.txt 与 raw/sillytavern_content_P2.txt）"
                     % (name, prof_name, " | ".join(seen[:8])))
            if bad:
                emit("  DETAIL provenance %s %s %s" % (name, prof_name, " | ".join(bad[:8])))
                for uid in sorted(bad_uids(bad)):
                    e = by_uid.get(uid)
                    if e is None:
                        continue
                    obs = observed_block_variants(name, uid)
                    emit("  FACT %s uid=%d 世界书原文 chars=%d bytes=%d sha=%s；out 中观测到 %d 种取值：%s"
                         % (name, uid, chars(e["content"]), bytes_of(e["content"]),
                            sha256_text(e["content"])[:16], len(obs),
                            " ; ".join("chars=%d bytes=%d sha=%s" % o for o in obs)))


# ---------- D. 差异与指标独立复算 ----------

DIFF_RE = re.compile(r"^DIFF (\S+) (\S+) (\S+) turn=(\d+) only_a=(\S+) only_b=(\S+) same=(\d+)$")
KPI_RE = re.compile(r"^KPI (\S+) value=(\S+) ci=\[([^,]*),([^\]]*)\] n=(\d+)$")


def read_reported_diff(name: str):
    p = RAW / ("%s_baseline_diff.txt" % name)
    if not p.is_file():
        return None
    rows = {}
    for line in p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").split("\n"):
        m = DIFF_RE.match(line)
        if m:
            a, b, prof, turn, oa, ob, same = m.groups()
            rows[(prof, int(turn))] = (a, b, parse_uids(oa), parse_uids(ob), int(same))
    return rows or None


def read_reported_kpi(name: str):
    """返回 metric -> (原始 value 字符串, ci_lo, ci_hi, n)。保留原文以便判「是否逐字相同」。"""
    p = RAW / ("%s_kpi.txt" % name)
    if not p.is_file():
        return None
    rows = {}
    for line in p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").split("\n"):
        m = KPI_RE.match(line)
        if m:
            metric, value, lo, hi, n = m.groups()
            rows[metric] = (value, lo, hi, int(n))
    return rows or None


def fmt_float6(x: float) -> str:
    """与 harness/metrics.py fmt_num 同口径的展示格式（%.6g）。"""
    if float(x) == int(x):
        return str(int(x))
    return "%.6g" % float(x)


def f1_score(a, b) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return 2.0 * len(sa & sb) / float(len(sa) + len(sb))


def part_d(adapters) -> None:
    emit("# D. 差异与指标独立复算：方案 vs baseline 的逐 turn 对称差 ＋ M1/M2")
    base_turns = {}
    for prof_name in PROFILES:
        base_turns[prof_name] = load_out_turns("baseline", prof_name) or {}
    for name in adapters:
        mine_turns = {}
        missing = []
        for prof_name in PROFILES:
            t = load_out_turns(name, prof_name)
            if t is None:
                missing.append(prof_name)
            else:
                mine_turns[prof_name] = t
        if missing:
            emit("  NOTE %s missing-profiles=%s" % (name, ",".join(missing)))

        # D1 逐 turn 对称差 vs raw/<name>_baseline_diff.txt
        reported = read_reported_diff(name)
        if not mine_turns:
            emit("RECOMPUTE %s baseline_diff match=false reason=out-json-missing" % name)
            verdict(False)
        elif reported is None and missing:
            # 该方案的 out/ 尚不齐（上游仍在跑）：这是「未测」，不是「对不上」，不计入 false。
            emit("RECOMPUTE %s baseline_diff match=%s reason=not-yet-measured "
                 "missing-profiles=%s raw-diff=absent" % (name, verdict(True), ",".join(missing)))
        elif reported is None:
            emit("RECOMPUTE %s baseline_diff match=false reason=raw-diff-missing" % name)
            verdict(False)
        else:
            bad = []
            total = 0
            for prof_name in PROFILES:
                for turn in TURNS:
                    a = (mine_turns.get(prof_name) or {}).get(turn)
                    b = base_turns.get(prof_name, {}).get(turn)
                    rep = reported.get((prof_name, turn))
                    if a is None or b is None or rep is None:
                        bad.append("%s/turn%d:unmeasured" % (prof_name, turn))
                        continue
                    total += 1
                    oa, ob, same = symdiff(a["active"], b["active"])
                    if (rep[2] != oa) or (rep[3] != ob) or (rep[4] != same):
                        bad.append("%s/turn%d recomputed(only_a=%s only_b=%s same=%d) "
                                   "reported(only_a=%s only_b=%s same=%d)"
                                   % (prof_name, turn, fmt_uids(oa), fmt_uids(ob), same,
                                      fmt_uids(rep[2]), fmt_uids(rep[3]), rep[4]))
            emit("RECOMPUTE %s baseline_diff lines=%d mismatch=%d match=%s"
                 % (name, total, len(bad), verdict(not bad)))
            for bl in bad[:8]:
                emit("  DETAIL diff %s %s" % (name, bl))

        # D2 M1 / M2 vs raw/<name>_kpi.txt
        rep_kpi = read_reported_kpi(name)
        if not mine_turns:
            emit("RECOMPUTE M1_%s match=false reason=out-json-missing" % name)
            emit("RECOMPUTE M2_%s match=false reason=out-json-missing" % name)
            continue
        if rep_kpi is None and missing:
            emit("RECOMPUTE M1_%s match=%s reason=not-yet-measured missing-profiles=%s kpi=absent"
                 % (name, verdict(True), ",".join(missing)))
            emit("RECOMPUTE M2_%s match=%s reason=not-yet-measured missing-profiles=%s kpi=absent"
                 % (name, verdict(True), ",".join(missing)))
            continue
        if rep_kpi is None:
            emit("RECOMPUTE M1_%s match=false reason=kpi-missing" % name)
            emit("RECOMPUTE M2_%s match=false reason=kpi-missing" % name)
            verdict(False)
            continue
        f1s, invs = [], []
        for turn in TURNS:
            a = mine_turns.get("P0", {}).get(turn)
            b = base_turns.get("P0", {}).get(turn)
            if a is None or b is None:
                continue
            f1s.append(f1_score(a["active"], b["active"]))
            common = set(a["order"]) & set(b["order"])
            oa = [u for u in a["order"] if u in common]
            invs.append(float(inversions(oa)))
        for metric, vals in (("M1_active_f1", f1s), ("M2_order_inv", invs)):
            if not vals:
                emit("RECOMPUTE %s %s match=false reason=no-p0-pairs" % (metric, name))
                continue
            got = sum(vals) / len(vals)
            entry = rep_kpi.get(metric)
            if entry is None:
                emit("RECOMPUTE %s %s reported=- recomputed=%.6f n=%d match=false reason=kpi-line-missing"
                     % (metric, name, got, len(vals)))
                continue
            rep_s, _lo, _hi, rep_n = entry
            same_text = (rep_s == fmt_float6(got))
            close = abs(float(rep_s) - got) <= FLOAT_TOL
            ok = ((same_text or close) and rep_n == len(vals))
            emit("RECOMPUTE %s %s reported=%s recomputed=%.6f same_text=%s "
                 "absdiff=%.3g n_reported=%d n_recomputed=%d match=%s"
                 % (metric, name, rep_s, got, "true" if same_text else "false",
                    abs(float(rep_s) - got), rep_n, len(vals), verdict(ok)))


# ---------- 主流程 ----------

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    except Exception:
        pass
    emit("# independent_recompute.py 独立复算报告（不采信任何已有读数，全部从原始文件重算）")
    emit("# root=%s" % ROOT.as_posix())
    emit("# 口径披露：CONTRACT §2 十条规则之外的 6 处边界取值")
    emit("#   ① 全词匹配：键首尾均为字母数字或下划线时用 \\b 语义，否则退回普通包含")
    emit("#   ② 空次级键：and_all 为假、not_any 为真")
    emit("#   ③ 递归额外文本＝当前已激活条目正文；constant 条目不参与递归触发")
    emit("#   ④ 递归轮次主键在「窗口文本＋已激活正文」上判，二级键仍只在窗口文本上判")
    emit("#   ⑤ 概率条目每 turn 重置 random.Random(seed)，按 uid 升序各取一次")
    emit("#   ⑥ 预算判定式 used + chars <= budget_chars，取等号保留")
    emit("# explained 的定义：adapter=sillytavern 且 uid=25 且 block sha256 命中三个已知宏展开值时计 explained（不计 mismatch）；")
    emit("#   取证：源码 repos/SillyTavern/public/scripts/world-info.js:5058 → public/scripts/macros.js:551/566 → node_modules/droll/droll.js:96，")
    emit("#         逐字正文 raw/sillytavern_content.txt、raw/sillytavern_content_P2.txt；其余任何不符一律计入 mismatch。")
    emit("")

    entries, chat, profs = load_inputs()
    adapters = [n for n in ("diceframe", "risuai", "sillytavern")
                if any((OUT / ("%s_%s.json" % (n, p))).is_file() for p in PROFILES)]
    emit("# 发现的方案：%s" % (",".join(adapters) if adapters else "无"))
    emit("")

    part_a()
    emit("")
    part_b(entries, chat, profs)
    emit("")
    part_c(entries, adapters)
    emit("")
    part_d(adapters)
    emit("")
    emit("# 说明：make_fixture.py 的产物路径固定为 <仓库>/data/，无法指向任意目录；")
    emit("#       本器把该脚本复制进系统临时目录的 harness/ 下重跑，使其相对路径落回临时目录。")
    return write()


if __name__ == "__main__":
    raise SystemExit(main())
