# -*- coding: utf-8 -*-
"""守卫：`scripts/evidence_check.py`（证据链三方对账）——断言 ＋ 定点变异自证。

对象：证据链校验件——把「引文快照 ←→ 快照清单 ←→ 测评数据 ←→ **本机复跑**」四方对起来，全程离线。
真源：`review/evidence/manifest.json`、`review/evidence/*`（README／package.json／实跑记录）、
`review/data/plugins.json`。
体例取自同仓 `tests/test_build_site.py`／`tests/test_bounty_list.py`／`tests/test_review_build.py`。

本件要证的核心命题：**引文是忠实的，且「本机复跑」的读数是可复算的**。故断言分四面：
  [S] 快照面：sha256 完整性 / 字节数 / 清单字段 / **反向遍历**（多出来的快照要点名）/
      缺件点名 / 清单坏结构 fail-closed / **本机复跑逐字节复算**
  [C] 出处面：每条 evidence 都写 doc、且 doc 在清单里
  [Q] 引文面：quotes 逐字命中且不短于下限；**篡改任一处都必须被点名**（这是本件存在的理由）

用法：
  python -X utf8 tests/test_evidence_check.py            # 正向：全部断言，末行「通过 N / 失败 M」
  python -X utf8 tests/test_evidence_check.py --quiet    # 只输出 `RED <id>` 与 `RAN <实跑数>`
  python -X utf8 tests/test_evidence_check.py --mutate   # 定点变异自证
  python -X utf8 tests/test_evidence_check.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中；1 = 有断言失败 / 变异未按预期转红；2 = ANCHOR-MISS。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

#: 本件会在仓内 import／子进程跑校验件——不许因此落下 `__pycache__`
#: （那会让 `git status` 变脏，也让「补丁全为新增」这条边界声明不成立）。
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                               # <仓根>
CHECK_REL = "scripts/evidence_check.py"
PROBE_REL = "scripts/evidence_probe.py"
MANIFEST_REL = "review/evidence/manifest.json"
DATA_REL = "review/data/plugins.json"
EVID_REL = "review/evidence"
SCAN = "scripts"

QUIET = "--quiet" in sys.argv
_red = []
#: 实跑断言计数：末行 N 由它给出（不手写常数），`--quiet` 也回报给父进程。
_RUN = [0]

# 生效条件：无必需形参时返回一个可写的沙箱根——**先试 `tempfile.mkdtemp()`，失败才回退**。
# 为什么要真写一次：本机 DSH 沙箱下 `mkdtemp()` 能建出目录，但目录**内**不可写（`WinError 5`）；
# 只看 mkdtemp 是否抛异常会把「不可写的临时目录」当可用。
def _pick_scratch_root():
    env = os.environ.get("REVIEW_SCRATCH_ROOT")
    if env:
        return env
    cand = ""
    try:
        cand = tempfile.mkdtemp(prefix="evidence_guard_")
        probe = os.path.join(cand, "write_probe")
        os.makedirs(os.path.join(probe, "x"), exist_ok=True)
        shutil.rmtree(probe, ignore_errors=True)
        return cand
    except OSError as exc:
        if cand:
            shutil.rmtree(cand, ignore_errors=True)
        fallback = os.path.join(os.path.dirname(ROOT), ".evidence_guard_tmp")
        try:
            os.makedirs(fallback, exist_ok=True)
        except OSError as exc2:
            raise SystemExit(
                "[错误] 守卫找不到可写的沙箱根：系统临时目录探针失败（%s）；"
                "回退目录 %s 也建不出来（%s）。可用环境变量 REVIEW_SCRATCH_ROOT "
                "指定一个可写目录。" % (exc, fallback, exc2))
        return fallback


SCRATCH_ROOT = _pick_scratch_root()
#: 清理权归**创建者**：父进程建根、父进程清；子进程（变异体守卫）只是借住，绝不整根 `rmtree`
#: ——否则会把父进程正在用的沙箱一起删掉（这是兄弟件 `test_review_build.py` 踩过的坑）。
_SCRATCH_OWNER = not os.environ.get("REVIEW_SCRATCH_ROOT")
RUN_TOKEN = uuid.uuid4().hex[:12]
_N = [0]


def ok(name, cond, detail=""):
    _RUN[0] += 1
    if not cond:
        _red.append(name.split(" ")[0])
    if QUIET:
        return
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                           "" if cond or not detail else "  · " + detail))


# 生效条件：无必需形参时返回一个全新可写的沙箱仓根（含探针、校验件、真源与**全部**快照）。
# 为什么必须复制**全部**快照而不是只复制 `.md`：快照目录现在还有 `*.package.json`（版本面）
# 与 `*.stdout.txt`（实跑记录）。只拷 `.md` 会让校验件的哈希核对、字节核对、反向遍历与
# 复算闸一起报错——那不是判据在判，是夹具缺件（早先版本就只拷 `.md`，一加新快照就崩）。
def make_sandbox():
    _N[0] += 1
    root = os.path.join(SCRATCH_ROOT, "ev_%s_%d" % (RUN_TOKEN, _N[0]))
    for rel in (CHECK_REL, PROBE_REL, MANIFEST_REL, DATA_REL):
        src = os.path.join(ROOT, *rel.split("/"))
        dst = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)
    src_ev = os.path.join(ROOT, *EVID_REL.split("/"))
    dst_ev = os.path.join(root, *EVID_REL.split("/"))
    os.makedirs(dst_ev, exist_ok=True)
    for name in os.listdir(src_ev):
        src = os.path.join(src_ev, name)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(dst_ev, name))
    return root


# 生效条件：root 为沙箱仓根、*args 为命令行参数时以子进程真跑校验件，返回 CompletedProcess。
def run_check(root, *args):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, "-X", "utf8", os.path.join(root, *CHECK_REL.split("/")),
         "--root", root, *args],
        cwd=root, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=300)


def _json(root, rel):
    with io.open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(root, rel, obj):
    with io.open(os.path.join(root, *rel.split("/")), "w",
                 encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 探针状态

BASE_RC = [None]          # 未篡改时的退出码
BASE_ERR = [""]
TAMPER = {}               # 场景名 -> (是否报不一致, 简要说明)


# 生效条件：scenario 为场景名、fn 为「在沙箱里做一处篡改」的函数、check 为「(rc, stdout, stderr) → 是否算检出」的谓词时，跑校验件并把结果记进 TAMPER。
def _tamper(scenario, fn, check=None):
    if scenario in TAMPER:
        return TAMPER[scenario]
    root = make_sandbox()
    fn(root)
    r = run_check(root)
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if check is None:
        check = lambda rc, so, se: rc == 1 and ((so or "") + (se or "")).strip() != ""  # noqa: E731
    detected = bool(check(r.returncode, r.stdout or "", r.stderr or ""))
    TAMPER[scenario] = (detected, "rc=%s out=%s" % (r.returncode, out[:90]))
    shutil.rmtree(root, ignore_errors=True)
    return TAMPER[scenario]


#: 各篡改场景的「算不算被检出」判据（源文件坏结构走 fail-closed 退出码 2，其余走不一致退出码 1）。
def _det_failclosed(rc, so, se):
    """输入坏结构：fail-closed 退出码 2 且报错在 stderr。"""
    return rc == 2 and "[错误]" in (se or "")


#: **判据必须点名**——这是本件最容易踩的坑，写清楚原因：
#: 同一处篡改常常会惊动不止一道闸。例如改一条引文，既会让「引文忠实」报错，**也会**让
#: 「本机复跑」的逐字节复算对不上——因为探针的输出里就印着各条证据的 doc 与引文。
#: 若用泛谓词（只要「有不一致」就算检出），短路其中一道闸时另一道仍会抓到它，
#: 对应的定点变异就**不会**让断言转红，于是变异被误判成 no-op。
#: 故每条拒绝面断言都必须检查**它自己那条判据的点名文本**。
def _det_named(*needles):
    """退出码 1 且明细里**点名**到指定判据文本。"""
    def check(rc, so, se):
        return rc == 1 and all(n in (so or "") for n in needles)
    return check


_det_hash = _det_named("快照哈希不符")
_det_missing = _det_named("快照缺失")
_det_doc_unknown = _det_named("出处不在清单")
_det_doc_missing = _det_named("出处未声明")
_det_quote_unfaithful = _det_named("引文不忠实")
_det_quote_missing = _det_named("引文未声明")
_det_quote_short = _det_named("引文过短")
_det_repro_diff = _det_named("复算不一致")
_det_repro_broken = _det_named("复算失败")
_det_snapshot_unlisted = _det_named("快照未登记")
_det_bytes = _det_named("字节数不符")


# ================================================================ 断言

def group_snapshot():
    print("[S] 快照面（sha256 完整性 / 缺件点名 / 清单坏结构 fail-closed）")
    root = make_sandbox()
    try:
        r = run_check(root)
        BASE_RC[0], BASE_ERR[0] = r.returncode, r.stderr or ""
        ok("S1 rc0 未篡改时校验件退出码 0（三方一致）", r.returncode == 0,
           "rc=%s err=%s" % (r.returncode, (r.stderr or "")[-140:]))
        ok("S2 out 未篡改时报告「全部一致」且打印快照数／引文条目数／复算条数",
           "全部一致" in (r.stdout or "") and "快照" in (r.stdout or "")
           and "引文条目" in (r.stdout or "") and "复算" in (r.stdout or ""))
        man = _json(root, MANIFEST_REL)
        docs = [d["file"] for d in man["documents"]]
        on_disk = sorted(n for n in os.listdir(os.path.join(root, *EVID_REL.split("/")))
                         if n != "manifest.json"
                         and os.path.isfile(os.path.join(root, *EVID_REL.split("/"), n)))
        ok("S3 cnt 快照清单条目数 == 目录里的快照文件数（**不限扩展名**：还有 package.json 与实跑记录）",
           len(docs) == len(on_disk), "清单 %s ／ 在盘 %s" % (sorted(docs), on_disk))
        real = True
        for d in man["documents"]:
            p = os.path.join(root, *EVID_REL.split("/"), d["file"])
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            real = real and (h == d.get("sha256"))
        ok("S4 hash 清单里的 sha256 与文件实际哈希逐份一致", real)
        ok("S5 tamper-md 改快照一个字节 ⇒ 校验件报「快照哈希不符」并点名该快照",
           _tamper("snapshot-bytes",
                   lambda rt: _append_byte(os.path.join(rt, *EVID_REL.split("/"),
                                                        _first_doc(rt))), _det_hash)[0])
        ok("S6 miss 删掉一份快照 ⇒ 校验件报「快照缺失」（缺件是「硬不一致」）",
           _tamper("snapshot-missing",
                   lambda rt: os.remove(os.path.join(rt, *EVID_REL.split("/"),
                                                     _first_doc(rt))), _det_missing)[0])
        ok("S7 badjson 清单坏 JSON ⇒ fail-closed 退出码 2",
           _tamper("manifest-bad",
                   lambda rt: _write_text(rt, MANIFEST_REL, "{not json"), _det_failclosed)[0])
        # S8–S13：**本机复跑逐字节复算**这道新闸的判据。早先版本证据的 output 可以是任何手写
        # 文字——「可复跑证据」根本没有机器判据。这六条把该闸钉住。
        r2 = run_check(root, "--repro")
        ok("S8 repro 未篡改时 --repro 退出码 0，且输出里报告「逐字节相同」",
           r2.returncode == 0 and "逐字节相同" in (r2.stdout or ""),
           "rc=%s out=%s" % (r2.returncode, (r2.stdout or "")[-120:]))
        ok("S9 tamper-repro 改一条「本机复跑」的 output 一个字节 ⇒ 点名「复算不一致」",
           _tamper("repro-bytes", _break_repro, _det_repro_diff)[0])
        ok("S10 tamper-probe 把 probe 换成不存在的 id ⇒ 点名复算失败",
           _tamper("probe-unknown", _unknown_probe, _det_repro_broken)[0])
        ok("S11 tamper-extra 目录里多一份**未登记**快照 ⇒ 点名「快照未登记」（反向遍历）",
           _tamper("snapshot-unregistered", _extra_snapshot, _det_snapshot_unlisted)[0])
        ok("S12 tamper-bytes 清单里的 bytes 写错 ⇒ 点名「字节数不符」",
           _tamper("manifest-bytes", _bad_bytes, _det_bytes)[0])
        ok("S13 tamper-short 引文短于下限 ⇒ 点名「引文过短」（短串在长文档里几乎必然命中）",
           _tamper("quote-short", _short_quote, _det_quote_short)[0])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def group_cite():
    print("[C] 出处面（每条 evidence 都声明 doc，且 doc 在清单里）")
    data = _json(ROOT, DATA_REL)
    man = _json(ROOT, MANIFEST_REL)
    docs = {d["file"] for d in man["documents"]}
    evs = [(rec["slug"], i, e) for rec in data["records"]
           for i, e in enumerate(rec.get("evidence") or [])]
    ok("C1 doc 每条 evidence 都写了 doc", all(str(e.get("doc") or "").strip()
                                               for _, _, e in evs))
    ok("C2 known 每条 doc 都在快照清单里",
       all(str(e.get("doc")) in docs for _, _, e in evs),
       str(sorted({str(e.get("doc")) for _, _, e in evs})))
    ok("C3 cover 每个插件至少 1 条证据带 doc（验收标准：≥1 条可复跑证据）",
       all(any(str(e.get("doc") or "").strip()
               for e in (rec.get("evidence") or [])) for rec in data["records"]))
    ok("C4 tamper-doc 把某条 doc 改成不存在的文件 ⇒ 校验件点名「出处不在清单」",
       _tamper("doc-unknown", _break_doc, _det_doc_unknown)[0])
    ok("C5 tamper-nodoc 删掉某条 doc ⇒ 校验件点名「出处未声明」",
       _tamper("doc-missing", _drop_doc, _det_doc_missing)[0])


def group_quote():
    print("[Q] 引文面（逐字命中；篡改必被点名——本件存在的理由）")
    data = _json(ROOT, DATA_REL)
    evs = [e for rec in data["records"] for e in (rec.get("evidence") or [])]
    ok("Q1 quotes 每条 evidence 的 quotes 都是非空字符串数组",
       all(isinstance(e.get("quotes"), list) and e["quotes"]
           and all(str(q).strip() for q in e["quotes"]) for e in evs))
    ok("Q2 cnt 引文总条数 ≥ 每条 evidence 1 条（验收下限）",
       sum(len(e["quotes"]) for e in evs) >= len(evs),
       "证据 %d 条 / 引文 %d 条" % (len(evs), sum(len(e["quotes"]) for e in evs)))
    ok("Q3 tamper-quote 改一个字的引文 ⇒ 校验件报「引文不忠实」并点名条目",
       _tamper("quote-edited", _break_quote, _det_quote_unfaithful)[0])
    ok("Q4 tamper-empty 把 quotes 清空 ⇒ 校验件点名「引文未声明」",
       _tamper("quote-empty", _empty_quote, _det_quote_missing)[0])
    ok("Q5 tamper-src 把某条引文换成另一份快照里的串 ⇒ 校验件报不忠实（出处与引文对不上）",
       _tamper("quote-wrongdoc", _wrong_doc, _det_quote_unfaithful)[0])


# ---------------------------------------------------------------- 篡改动作

def _first_doc(root):
    man = _json(root, MANIFEST_REL)
    return man["documents"][0]["file"]


def _append_byte(p):
    with open(p, "ab") as fh:
        fh.write(b"\n")


def _write_text(root, rel, text):
    with io.open(os.path.join(root, *rel.split("/")), "w",
                 encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _edit_first_evidence(root, fn):
    data = _json(root, DATA_REL)
    fn(data["records"][0]["evidence"][0])
    _write_json(root, DATA_REL, data)


def _break_doc(root):
    _edit_first_evidence(root, lambda e: e.__setitem__("doc", "no-such-doc.md"))


def _drop_doc(root):
    _edit_first_evidence(root, lambda e: e.pop("doc", None))


def _break_quote(root):
    _edit_first_evidence(root, lambda e: e["quotes"].__setitem__(
        0, str(e["quotes"][0]) + "（篡改）"))


def _empty_quote(root):
    _edit_first_evidence(root, lambda e: e.__setitem__("quotes", []))


def _wrong_doc(root):
    man = _json(root, MANIFEST_REL)
    other = [d["file"] for d in man["documents"]
             if d["file"] != man["documents"][0]["file"]][0]
    _edit_first_evidence(root, lambda e: e.__setitem__("doc", other))


# ---------------------------------------------------------------- 复算面的篡改动作

def _edit_first_local(root, fn):
    """改一条 `kind == 本机复跑` 的证据，然后写回（复算闸只认这一档）。"""
    data = _json(root, DATA_REL)
    for rec in data["records"]:
        for e in rec.get("evidence") or []:
            if e.get("kind") == "本机复跑":
                fn(e)
                _write_json(root, DATA_REL, data)
                return
    raise AssertionError("真源里没有「本机复跑」证据——复算面的判据无从判起")


def _break_repro(root):
    """把「本机复跑」的 output 改一个字节（探针 stdout 里的 `sha256` → `sha257`）。"""
    _edit_first_local(root, lambda e: e.__setitem__(
        "output", str(e.get("output") or "").replace("sha256", "sha257", 1)))


def _unknown_probe(root):
    _edit_first_local(root, lambda e: e.__setitem__("probe", "no.such.probe"))


def _extra_snapshot(root):
    d = os.path.join(root, *EVID_REL.split("/"))
    with io.open(os.path.join(d, "unregistered.snapshot.txt"), "w",
                 encoding="utf-8", newline="\n") as fh:
        fh.write("这份快照没有登记在 manifest.json 里\n")


def _bad_bytes(root):
    man = _json(root, MANIFEST_REL)
    man["documents"][0]["bytes"] = int(man["documents"][0].get("bytes") or 0) + 1
    _write_json(root, MANIFEST_REL, man)


def _short_quote(root):
    """把首条引文截到 5 字符——它在快照里**仍然存在**，故这条只惊动「引文过短」那道闸。"""
    _edit_first_evidence(root, lambda e: e["quotes"].__setitem__(
        0, str(e["quotes"][0])[:5]))


def judge():
    del _red[:]
    TAMPER.clear()
    group_snapshot()
    group_cite()
    group_quote()
    return list(_red)


# ================================================================ 定点变异

MUTATIONS = (
    ("E1", CHECK_REL,
     '        got = sha256_file(p)',
     '        got = want  # MUT', {"S5"}),
    ("E2", CHECK_REL,
     '        if not os.path.isfile(p):',
     '        if False:  # MUT', {"S6"}),
    ("E3", CHECK_REL,
     '                bad.append("出处未声明：%s 没写 doc（引文出自哪个快照）" % eid)',
     '                pass  # MUT', {"C5"}),
    ("E4", CHECK_REL,
     '                bad.append("出处不在清单：%s 写的 doc=%r 不在 manifest.json" % (eid, doc))',
     '                pass  # MUT', {"C4"}),
    ("E5", CHECK_REL,
     '            miss = [q for q in quotes if str(q) not in text]',
     '            miss = []  # MUT', {"Q3", "Q5"}),
    ("E6", CHECK_REL,
     '                bad.append("引文未声明：%s 没写 quotes（从快照里摘了哪些话）" % eid)',
     '                pass  # MUT', {"Q4"}),
)


def _anchor_preflight():
    src = io.open(os.path.join(ROOT, *CHECK_REL.split("/")), encoding="utf-8").read()
    bad = [(mid, src.count(old)) for mid, _rel, old, _new, _exp in MUTATIONS
           if src.count(old) != 1]
    if not bad:
        return 0
    for mid, n in bad:
        print("  ANCHOR-MISS %s：锚点命中 %d 次（期望 1）" % (mid, n))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _run_quiet(root):
    """以 `--quiet` 在 root 下重跑本守卫，返回 (红项集合, 实跑断言数)。

    **为什么要读回实跑数**：只看 `RED <id>` 行的话，若某变异让守卫吐完「恰好期望的那些红项」
    之后崩在中途，红项集合仍相等，变异被误判 PASS——判据空转。故子进程回报 `RAN <实跑数>`，
    父进程同时校验。
    """
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1")
    #: 子进程借住父进程的沙箱根，且**不清理**它（清理权在 `_SCRATCH_OWNER`）。
    env["REVIEW_SCRATCH_ROOT"] = SCRATCH_ROOT
    r = subprocess.run(
        [sys.executable, "-X", "utf8",
         os.path.join(root, "tests", "test_evidence_check.py"), "--quiet"],
        cwd=root, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=900)
    red = set(l.split()[1] for l in (r.stdout or "").splitlines() if l.startswith("RED "))
    m = re.search(r"^RAN (\d+)$", r.stdout or "", re.M)
    return red, (int(m.group(1)) if m else -1)


def _mutate_mode():
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：逐条短路一条判据，对应断言必须**恰好**转红\n")
    base_red, base_ran = _run_quiet(ROOT)
    print("  未变异基线：红项 %s（实跑断言 %d）"
          % (sorted(base_red) or "无（应为无）", base_ran))
    bad = []
    if base_red:
        bad.append("基线即转红：%s" % sorted(base_red))
    if base_ran != ASSERT_TOTAL:
        bad.append("基线实跑断言数 %d ≠ 期望 %d——判据没跑全，变异自证不可信"
                   % (base_ran, ASSERT_TOTAL))
    for mid, rel, old, new, expect in MUTATIONS:
        root = make_sandbox()
        try:
            for f in (CHECK_REL, "tests/test_evidence_check.py"):
                dst = os.path.join(root, *f.split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy(os.path.join(ROOT, *f.split("/")), dst)
            p = os.path.join(root, *rel.split("/"))
            t = io.open(p, encoding="utf-8").read()
            io.open(p, "w", encoding="utf-8", newline="\n").write(t.replace(old, new, 1))
            red, ran = _run_quiet(root)
            hit = (red == set(expect)) and (ran == ASSERT_TOTAL)
            if not hit:
                bad.append("%s：红项 %s ≠ 期望 %s，或实跑断言数 %d ≠ %d"
                           % (mid, sorted(red), sorted(expect), ran, ASSERT_TOTAL))
            print("  [%s] %s：红项 %d（期望 %d）实跑 %d%s"
                  % ("PASS" if hit else "FAIL", mid, len(red), len(expect), ran,
                     "" if hit else " 实=%s 期=%s" % (sorted(red), sorted(expect))))
        finally:
            shutil.rmtree(root, ignore_errors=True)
    print("\n定点变异：%s" % ("PASS（逐条恰好命中期望红项）" if not bad
                              else "FAIL —— " + "；".join(bad)))
    print("通过 %d / 失败 %d（变异 %d 组）"
          % (len(MUTATIONS) - len(bad), len(bad), len(MUTATIONS)))
    return 0 if not bad else 1


#: 断言总数不手写常数：S 组 13 ＋ C 组 5 ＋ Q 组 5。末行打印**实跑计数**，
#: 与它不等即判红（少跑不许伪装成通过）。`--quiet` 不跳过任何一条，故两处同值。
ASSERT_TOTAL = 13 + 5 + 5


def main():
    if "--list" in sys.argv:
        for mid, rel, _old, _new, exp in MUTATIONS:
            print("  %s  target=%-28s expect_red=%s" % (mid, rel, sorted(exp)))
        return 0
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode()
        red = judge()
        actual = _RUN[0]
        if QUIET:
            for r in sorted(set(red)):
                print("RED %s" % r)
            #: 回报**实跑断言数**：父进程据此判定「判据是跑完了，还是崩在中途」。
            print("RAN %d" % actual)
            return 1 if red else 0
        print()
        if actual != ASSERT_TOTAL:
            print("!! 实跑断言数 %d ≠ 期望 %d —— 有判据没跑到（少跑不等于通过）"
                  % (actual, ASSERT_TOTAL))
            red.append("ASSERT-COUNT")
        print("通过 %d / 失败 %d（实跑断言 %d）"
              % (ASSERT_TOTAL - len(set(red)), len(set(red)), actual))
        if red:
            print("红项：%s" % sorted(set(red)))
        return 1 if red else 0
    finally:
        if _SCRATCH_OWNER:
            shutil.rmtree(SCRATCH_ROOT, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
