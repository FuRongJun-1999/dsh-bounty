# -*- coding: utf-8 -*-
"""守卫：`scripts/evidence_check.py`（证据链三方对账）——断言 ＋ 定点变异自证。

对象：证据链校验件——把「引文快照 ←→ 快照清单 ←→ 测评数据 ←→ **本机复跑**」四方对起来，全程离线。
真源：`review/evidence/manifest.json`、`review/evidence/*`（README／package.json／实跑记录）、
`review/data/plugins.json`。
体例取自同仓 `tests/test_build_site.py`／`tests/test_bounty_list.py`／`tests/test_review_build.py`。

本件要证的核心命题：**引文是忠实的，且「本机复跑」的读数是可复算的**。故断言分五面：
  [S] 快照面：sha256 完整性 / 字节数 / 清单字段 / **反向遍历**（多出来的快照要点名）/
      缺件点名 / 清单坏结构 fail-closed / **本机复跑逐字节复算**
  [C] 出处面：每条 evidence 都写 doc、且 doc 在清单里
  [Q] 引文面：quotes 逐字命中且不短于下限；**篡改任一处都必须被点名**（这是本件存在的理由）
  [A] 基座面：**评分基座对账**（`evidence_check.py` 的 ③b 段）——`dim_basis` 指向的证据须过
      快照／引文／复跑三道闸、下标不得越界、5 分维必须挂本机复跑、`null` 与 `unmeasured_dims`
      双向一致、顶层 `rubric_version` 必须在场；并**逐记录逐维**对照 `review_build.dim_tiers()`——
      两份**独立实现**在同一份真源上必须给出同一张档位表（谁单独改口径，另一份就打脸）。

用法：
  python -X utf8 tests/test_evidence_check.py            # 正向：全部断言，末行「通过 N / 失败 M」
  python -X utf8 tests/test_evidence_check.py --quiet    # 只输出 `RED <id>` 与 `RAN <实跑数>`
  python -X utf8 tests/test_evidence_check.py --mutate   # 定点变异自证
  python -X utf8 tests/test_evidence_check.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中；1 = 有断言失败 / 变异未按预期转红；2 = ANCHOR-MISS。
"""
from __future__ import annotations

import hashlib
import importlib.util
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
BUILD_REL = "scripts/review_build.py"
MANIFEST_REL = "review/evidence/manifest.json"
DATA_REL = "review/data/plugins.json"
EVID_REL = "review/evidence"
SCAN = "scripts"

#: 已提交真源的确切路径——整轮自证里**只读**（变异绝不写回交付物）。
COMMITTED_DATA = os.path.join(ROOT, *DATA_REL.split("/"))
#: **[A] 组**读的真源路径，**允许被环境变量覆盖**。
#: 定点变异自证把 `EVIDENCE_DATA_SRC` 指向一份**临时副本**，于是两件事同时成立：
#:   ① 数据面变异永远不落到已提交真源上（交付物不会被自证过程改脏）；
#:   ② 只有 [A] 组读它——[S]/[C]/[Q] 组读 `ROOT` 下那份已提交真源，
#:      故数据面变异才可能让红项集合**恰好一条**（多红即语义纠缠）。
DATA_SRC = os.environ.get("EVIDENCE_DATA_SRC") or COMMITTED_DATA

#: 维度数——**守卫侧独立声明**（本件不 import 被守卫对象，也不问生成器）：
#: 若写成 `len(review_build.DIMENSIONS)`，两份实现一起漂移就看不出来了，
#: A19 的「15 格」也会跟着缩水而永远通过。五维口径见 `review/data/plugins.json` 的 `_schema`。
N_DIMS = 5

QUIET = "--quiet" in sys.argv
_red = []
#: 实跑断言计数：末行 N 由它给出（不手写常数），`--quiet` 也回报给父进程。
_RUN = [0]

# 生效条件：base 为已存在的目录时，在其中建一个**唯一名**空目录并返回它。
# ★ **刻意不用 `tempfile.mkdtemp()`**——本机 DSH 沙箱下它建出来的目录是**废的**：
#   往里建子目录报 `WinError 5`、连 `os.rmdir()` 它自己都报 `WinError 5`，
#   `icacls` 连 DACL 都读不出来（`Failed processing 1 files`，rc=5）。
#   同一进程、同一父目录下的最小对照（都实测过）：
#       os.mkdir(d, 0o700)          → 子目录建不进去、d 也删不掉   ← `mkdtemp()` 内部就是这一句
#       os.mkdir(d) / os.makedirs(d)→ 一切正常，整棵树 `rmtree` 删得干净
#       os.chmod(d, 0o700)（建完再改）→ 不影响（Windows 上 chmod 只翻只读位）
#   即：**`os.mkdir` 的 mode 实参**在 Windows 上落成了一个拒绝项。故这里一律用
#   `os.makedirs()` 建目录——权限收窄由沙箱自己管，判据不该为此在环境里留清不掉的东西。
def _unique_scratch_dir(base):
    for _ in range(64):
        d = os.path.join(base, "evidence_guard_%s" % uuid.uuid4().hex[:8])
        try:
            os.makedirs(d)
        except FileExistsError:                    # 撞名就换一个（`mkdtemp` 语义）
            continue
        return d
    raise OSError("建不出唯一名沙箱目录：%s" % base)


# 生效条件：无必需形参时返回一个可写的沙箱根——**先试系统临时目录，失败才回退**。
# 为什么要真写**并且真删**一次：本机 DSH 沙箱下「建得出来」不等于「用得起来」——
# 目录内可能不可写（`WinError 5`）、还可能删不掉；只看 mkdtemp 是否抛异常会把这种位置当可用。
# 探针里的 `rmtree` **不再 ignore_errors**：删不掉就说明这个位置用完也清不掉，直接换地方。
def _pick_scratch_root():
    env = os.environ.get("REVIEW_SCRATCH_ROOT")
    if env:
        return env
    cand = ""
    try:
        cand = _unique_scratch_dir(tempfile.gettempdir())
        probe = os.path.join(cand, "write_probe")
        os.makedirs(os.path.join(probe, "x"))      # 目录内可写
        shutil.rmtree(probe)                       # 目录内**删得掉**（删不掉即换地方）
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


# 生效条件：无必需形参时尽力删掉沙箱根，返回「是不是真的删掉了」——**不静默**。
# 为什么不再 `ignore_errors=True` 了事：删除失败曾经被静默吞掉——本机沙箱下 `mkdtemp()`
# 建的沙箱根根本删不掉（成因与修法见 `_unique_scratch_dir()`），于是「清过了」是假的，
# 每跑一次就在环境里攒一个空壳而无人知晓。改用 `os.makedirs()` 之后已能删干净；
# 这一层是**兜底**：万一还有别的拒绝面，至少让命令行上有人看见这一行。
def _drop_scratch_root() -> bool:
    shutil.rmtree(SCRATCH_ROOT, ignore_errors=True)
    try:
        os.lstat(SCRATCH_ROOT)
    except FileNotFoundError:
        return True                                # 真删掉了
    except OSError:
        return False                               # 还在（连 stat 都被拒）
    return False


def ok(name, cond, detail=""):
    _RUN[0] += 1
    if not cond:
        _red.append(name.split(" ")[0])
    if QUIET:
        return
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                           "" if cond or not detail else "  · " + detail))


# 生效条件：无必需形参时返回一个全新可写的沙箱仓根（含探针、校验件、**整目录真源**与全部快照）。
# 为什么必须复制**全部**快照而不是只复制 `.md`：快照目录现在还有 `*.package.json`（版本面）
# 与 `*.stdout.txt`（实跑记录）。只拷 `.md` 会让校验件的哈希核对、字节核对、反向遍历与
# 复算闸一起报错——那不是判据在判，是夹具缺件（早先版本就只拷 `.md`，一加新快照就崩）。
# 同理，真源必须**整目录**拷 `review/data/**`：`rubric.json`（判据真源）与 `plugins.json`
# 是配套的，只拷一件就是夹具缺件。`review_build.py` 也进沙箱——[A] 组要拿**同一份真源**
# 同时问两个独立实现，沙箱里那一份实现才与沙箱里那一份真源配套。
def make_sandbox():
    _N[0] += 1
    root = os.path.join(SCRATCH_ROOT, "ev_%s_%d" % (RUN_TOKEN, _N[0]))
    for rel in (CHECK_REL, PROBE_REL, BUILD_REL, MANIFEST_REL):
        src = os.path.join(ROOT, *rel.split("/"))
        dst = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)
    src_data = os.path.join(ROOT, "review", "data")
    dst_data = os.path.join(root, "review", "data")
    os.makedirs(dst_data, exist_ok=True)
    for name in os.listdir(src_data):
        src = os.path.join(src_data, name)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(dst_data, name))
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


# ---------------------------------------------------------------- [A] 组取数的三个小工具

# 生效条件：name 为模块名、path 为实现文件路径时载入并返回该模块。
# 一律从**沙箱里那一份**载入：变异体守卫据此读到变异后的实现（否则判据空转）。
def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 生效条件：root 为沙箱仓根、want_repro 为「要不要连复算闸一起判」时返回 audit() 的 (rows, bad)。
# 为什么直接读返回值、不解析 stdout：本组判的就是对账的**结果**（点名集合与档位表），
# 文本输出只是它的一个投影；拿投影当判据，改一行措辞就能让判据空转。
def _audit(root, want_repro=True):
    return _load_module("evidence_check_for_guard",
                        os.path.join(root, *CHECK_REL.split("/"))).audit(
        root, want_repro=want_repro)


# 生效条件：bad 为不一致行列表、needle 为判据点名文本时返回其中含该文本的行。
def _hits(bad, needle):
    return [b for b in bad if needle in b]


# 生效条件：mutate 为 None 时返回「plugins.json 取 DATA_SRC」的沙箱；否则在**已提交真源**上改一处再落进沙箱。
# 为什么要分两支（如实声明这是刻意的）：
#   · 正向判据必须看 `DATA_SRC`——变异模式下它被换成改过一处的临时副本，
#     「该报的报」才会随数据面变异转红；
#   · 反向（篡改）判据一律从**已提交真源**出发——否则一个数据面变异会让每条断言的反向用例
#     一起读到同一处坏数据，红项集合再也不可能「恰好一条」。
def _data_root(mutate=None):
    root = make_sandbox()
    if mutate is None:
        shutil.copy(DATA_SRC, os.path.join(root, *DATA_REL.split("/")))
    else:
        with io.open(COMMITTED_DATA, encoding="utf-8") as fh:
            doc = json.load(fh)
        mutate(doc)
        _write_json(root, DATA_REL, doc)
    return root


#: `basis` 对账行的 detail 形如「分数 4 ／ 档位 reading ／ 基座 2 条」——档位从这里读**它报的值**。
_ROW_TIER_RE = re.compile(r"档位\s+(none|prose|reading|repro)\s*／")


# 生效条件：rows 为 audit() 的对账行时返回 evidence_check **自己报的**档位表 {slug: {维度: 档位}}。
def _ec_tiers(rows):
    out = {}
    for r in rows:
        if r.get("kind") != "basis":
            continue
        slug, _, dim = str(r.get("id") or "").partition("#")
        m = _ROW_TIER_RE.search(str(r.get("detail") or ""))
        if slug and dim and m:
            out.setdefault(slug, {})[dim] = m.group(1)
    return out


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


# ---------------------------------------------------------------- [A] 基座面（③b 段）

#: [A] 组的判据全部针对 `evidence_check.audit()` 的返回 `(rows, bad)`，**不解析 stdout**：
#: 一条断言必须有两面——坏数据 ⇒ `bad` 里出现**它自己那条**点名（该报的报）；
#: 好数据 ⇒ 见 A20（`bad == []`，不该报的不报）。
#: 为什么每条的「不报」面都只查**自己那条**点名文本，而不是整份 `bad`：
#: 数据面变异一次只该让一条断言转红。若「不报」面写成 `bad == []`，任何一处变异都会
#: 连带把**所有** A 组断言拖红，红项集合就不再「恰好相等」，定点变异失去分辨力。
#: 「整份 bad 必须为空」由 A20 单独负责（它读**已提交真源**，故不受任何数据面变异影响）。
def group_basis():
    print("[A] 基座面（评分基座对账：与生成器**相互独立地**再判一遍）")
    clean = make_sandbox()
    rows0, bad0 = _audit(clean)
    doc0 = _json(clean, DATA_REL)
    n_rec = len(doc0["records"])
    n_basis = len([r for r in rows0 if r.get("kind") == "basis"])
    n_sum = len([r for r in rows0 if r.get("kind") == "basis-sum"])

    # 以下正向判据一律看 `DATA_SRC`（变异模式下是改过一处的临时副本）。
    root = _data_root()
    rows, bad = _audit(root)
    doc = _json(root, DATA_REL)

    # A14：基座指向的证据必须同时通过**既有的**快照／引文／复跑三道闸。
    # 反向用例接受「任意一道闸点名该 eid」——这正是它作为**三闸合并**判据的意义：
    # 若引文闸被短路（既有变异 E5），复算闸仍会点名同一条证据（探针 stdout 里印着引文原文）。
    # 「引文闸本身」的定点变异由 Q3／Q5 负责，两处刻意不重叠。
    # 只统计**下标在范围内**的引用：越界是 A15 的判据面，不在本条里重复。
    refs = []
    for rec in doc["records"]:
        evs = rec.get("evidence") or []
        for dim, basis in (rec.get("dim_basis") or {}).items():
            for i in _idx(basis):
                if 0 <= i < len(evs):
                    refs.append("%s#%d" % (rec.get("slug"), i))
    dirty = sorted({e for e in refs if any(e in b for b in bad)})
    broken_root = _data_root(_break_referenced_quote)
    bad_broken = _audit(broken_root)[1]
    eid_broken = _referenced_local_eid(doc0)
    named = sorted({e for e in refs if any(e in b for b in bad_broken)})
    ok("A14 basis-reconciled 基座引用的证据须过三道闸（好数据零点名；改坏一条即被点名）",
       bool(refs) and not dirty and named == [eid_broken],
       "基座引用 %d 条／好数据被点名=%s／改坏 %s 后被点名=%s"
       % (len(refs), dirty[:3], eid_broken, named[:3]))

    # A15：基座下标越界 ⇒ 点名（**与生成器独立实现**：生成器侧另有一套 `_basis_entries` 跳过越界）。
    tgt15 = _first_basis_dim(doc0)
    b15 = _audit(_data_root(_basis_index_oob), want_repro=False)[1]
    n15 = _hits(b15, "评分基座下标越界")
    ok("A15 basis-index-range 基座下标越界必点名（好数据无此点名；改成 99 后**恰好**点这一条）",
       not _hits(bad, "评分基座下标越界")
       and len(n15) == 1 and ("%s 的 %s" % tgt15) in n15[0] and "99" in n15[0],
       "变异靶=%s ／ 坏数据点名=%s" % (tgt15, n15))

    # A16：5 分维的基座里没有本机复跑 ⇒ 点名（**与生成器独立实现**：生成器读 rubric 的 must）。
    tgt16 = _first_five_transcribed_dim(doc0)
    b16 = _audit(_data_root(_five_no_local), want_repro=False)[1]
    n16 = _hits(b16, "5 分无本机复跑")
    ok("A16 five-needs-repro 5 分维基座无本机复跑 ⇒ 必点名（好数据无此点名）",
       not _hits(bad, "5 分无本机复跑")
       and len(n16) == 1 and ("%s 的 %s" % tgt16) in n16[0],
       "变异靶=%s ／ 坏数据点名=%s" % (tgt16, n16))

    # A17：**双向**一致——null 维必须在 unmeasured_dims；非 null 维不得在内。两个方向各一个反向用例。
    tgt17a = _first_null_dim(doc0)
    tgt17b = _first_scored_dim(doc0)
    n17a = _hits(_audit(_data_root(_null_out_of_um), want_repro=False)[1], "未测维度未登记")
    n17b = _hits(_audit(_data_root(_scored_into_um), want_repro=False)[1], "已评分维度被列为未测")
    ok("A17 null-vs-unmeasured `null` 维须在 unmeasured_dims、非 null 维不得在内（两向都点名；好数据都不点名）",
       not _hits(bad, "未测维度未登记") and not _hits(bad, "已评分维度被列为未测")
       and len(n17a) == 1 and ("%s 的 %s" % tgt17a) in n17a[0]
       and len(n17b) == 1 and ("%s 的 %s" % tgt17b) in n17b[0],
       "null 向=%s ／ 有分向=%s" % (n17a, n17b))

    # A18：顶层 rubric_version 必须在场（口径不自版本化就无法复审）。
    n18 = _hits(_audit(_data_root(_drop_rubric_version), want_repro=False)[1],
                "真源缺 rubric_version")
    ok("A18 rubric-version-present 顶层 rubric_version 在场（好数据不点名；删掉后**恰好**点这一条）",
       not _hits(bad, "真源缺 rubric_version") and len(n18) == 1
       and str(doc0.get("rubric_version") or "").strip() != "",
       "坏数据点名=%s" % n18)

    # A19：**两份独立实现必须说同一件事**——把 `evidence_check` ③b 段**报出来的**档位表与
    # `review_build.dim_tiers()` 逐记录逐维对照（现行真源 3 条记录 × 5 维 = 15 格）。
    # 这条是本件唯一一处**跨实现**判据：两边各判一遍，谁单独改口径（改档位推导、改读数正则、
    # 改维度名）都会被另一份打脸。对照的是「同一份真源」（DATA_SRC），故数据面变异同时被两边看到。
    ec_tiers = _ec_tiers(rows)
    rb = _load_module("review_build_for_guard", os.path.join(root, *BUILD_REL.split("/")))
    cells, mism = 0, []
    for rec in doc["records"]:
        want = rb.dim_tiers(rec)
        for dim in rb.DIMENSIONS:
            cells += 1
            got = ec_tiers.get(str(rec.get("slug")), {}).get(dim)
            if got != want.get(dim):
                mism.append("%s/%s：evidence_check=%s ／ review_build=%s"
                            % (rec.get("slug"), dim, got, want.get(dim)))
    ok("A19 tiers-agree 两份独立实现（evidence_check ③b ／ review_build.dim_tiers）在同一份真源上"
       "逐记录逐维档位相同（%d 格全等）" % cells,
       cells == n_rec * N_DIMS and not mism, "；".join(mism[:3]))

    # A20：**不该报的不报**——已提交真源上 `audit()` 的 `bad` 必须为空（连复算闸一起判），
    # 且对账行按「记录 × 五维」齐备（防「一行都没产出」被当成零点名而误判通过）。
    # 与 S1 的关系（如实声明，不假装独立）：S1 判退出码，本条判 `bad` 这份**结构化**结果；
    # 两者是同一判据的两个投影，刻意都留着——退出码可以被别的路径改写，`bad` 才是判据的原话。
    ok("A20 audit-clean 已提交真源上 audit() 零点名（bad == []）且基座行按「记录 × 五维」齐备",
       bad0 == [] and n_basis == n_rec * N_DIMS and n_sum == n_rec,
       "bad=%s ／ 基座行 %d（应 %d）／ 汇总行 %d（应 %d）"
       % (bad0[:2], n_basis, n_rec * N_DIMS, n_sum, n_rec))


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


# ------------------------------------------------- [A] 组用：基座面的数据变异（靶 ＋ 动作）

#: 本机复跑的类型名（对账件与生成器同口径；两处漂移会被 A19 与 5 分判据一起打脸）。
LOCAL_KIND = "本机复跑"


# 生效条件：basis 为 `dim_basis` 的原值时返回其中**合法整数**下标（bool 不算 int）。
def _idx(basis):
    return [i for i in (basis if isinstance(basis, list) else [])
            if isinstance(i, int) and not isinstance(i, bool)]


def _rec(doc, slug):
    for r in doc["records"]:
        if r.get("slug") == slug:
            return r
    raise AssertionError("真源里没有记录 %s" % slug)


# 下面这些「找靶」函数都遍历**真源自己的键序**（不另立一份维度表），故真源改维序也不空转。
def _first_basis_dim(doc):
    """第一个挂了证据的（记录, 维度）——A15 的变异靶。"""
    for r in doc["records"]:
        for dim in (r.get("dim_basis") or {}):
            if _idx(r["dim_basis"][dim]):
                return (r["slug"], dim)
    raise AssertionError("真源里没有任何挂了证据的维度——A15 无从判起")


def _first_five_transcribed_dim(doc):
    """第一个「记 5 分且基座含非本机复跑条目」的（记录, 维度）——A16 的变异靶。"""
    for r in doc["records"]:
        evs = r.get("evidence") or []
        for dim, score in (r.get("dimensions") or {}).items():
            if score != 5:
                continue
            keep = [i for i in _idx((r.get("dim_basis") or {}).get(dim))
                    if 0 <= i < len(evs)
                    and str(evs[i].get("kind") or "") != LOCAL_KIND]
            if keep:
                return (r["slug"], dim)
    raise AssertionError("真源里没有「5 分且基座含转引条目」的维度——A16 无从判起")


def _first_null_dim(doc):
    """第一个「记 `null` 且已登记在 unmeasured_dims」的（记录, 维度）——A17 的变异靶之一。"""
    for r in doc["records"]:
        um = r.get("unmeasured_dims")
        if not isinstance(um, list):
            continue
        for dim, v in (r.get("dimensions") or {}).items():
            if v is None and dim in um:
                return (r["slug"], dim)
    raise AssertionError("真源里没有「记 null 且在 unmeasured_dims」的维度——A17 无从判起")


def _first_scored_dim(doc):
    """第一个「有分数且**不在** unmeasured_dims」的（记录, 维度）——A17 的变异靶之二。"""
    for r in doc["records"]:
        um = r.get("unmeasured_dims") or []
        for dim, v in (r.get("dimensions") or {}).items():
            if v is not None and dim not in um:
                return (r["slug"], dim)
    raise AssertionError("真源里没有「有分数且不在 unmeasured_dims」的维度——A17 无从判起")


def _referenced_local_eid(doc):
    """第一个「被某个 dim_basis 引用、且 kind == 本机复跑」的证据 eid。"""
    for r in doc["records"]:
        evs = r.get("evidence") or []
        for dim in (r.get("dim_basis") or {}):
            for i in _idx(r["dim_basis"][dim]):
                if 0 <= i < len(evs) and str(evs[i].get("kind") or "") == LOCAL_KIND:
                    return "%s#%d" % (r["slug"], i)
    raise AssertionError("真源里没有任何「被 dim_basis 引用」的本机复跑证据——A14 无从判起")


# 生效条件：doc 为真源对象时就地改坏一处，只动**基座面**该动的那一格（其余判据面不受牵连）。
def _basis_index_oob(doc):
    """A15／`Mn-a`：把某维的基座下标改成越界值（证据只有个位数条，99 必然越界）。"""
    slug, dim = _first_basis_dim(doc)
    _rec(doc, slug)["dim_basis"][dim] = [99]


def _five_no_local(doc):
    """A16／`Mn-b`：把某个 5 分维的基座收成**纯转引**（保留第一条转引，去掉本机复跑）。"""
    slug, dim = _first_five_transcribed_dim(doc)
    r = _rec(doc, slug)
    evs = r.get("evidence") or []
    r["dim_basis"][dim] = [i for i in _idx(r["dim_basis"][dim])
                           if str(evs[i].get("kind") or "") != LOCAL_KIND][:1]


def _null_out_of_um(doc):
    """A17／`Mn-c`：把一个记 `null` 的维度移出 `unmeasured_dims`（单向失配）。"""
    slug, dim = _first_null_dim(doc)
    _rec(doc, slug)["unmeasured_dims"].remove(dim)


def _scored_into_um(doc):
    """A17／`Mn-f`：把一个**有分数**的维度塞进 `unmeasured_dims`（反方向失配）。"""
    slug, dim = _first_scored_dim(doc)
    _rec(doc, slug)["unmeasured_dims"].append(dim)


def _drop_rubric_version(doc):
    """A18／`Mn-d`：删掉顶层 `rubric_version`（口径不自版本化）。"""
    doc.pop("rubric_version", None)


def _break_referenced_quote(doc):
    """A14／`Mn-e`：把一条**被 dim_basis 引用**的「本机复跑」证据的首条引文改坏。

    为什么挑「被基座引用的本机复跑证据」：这样坏掉的**不止**引文闸——探针 stdout 里印着
    各条引文的原文，故复算闸也会点火（复算不一致）。两道闸都会点名同一条 eid，
    于是 A14 这条**三闸合并**的判据在引文闸被短路时（既有变异 E5）依然成立。
    """
    eid = _referenced_local_eid(doc)
    slug, _, i = eid.partition("#")
    ev = _rec(doc, slug)["evidence"][int(i)]
    ev["quotes"][0] = str(ev["quotes"][0]) + "（基座变异）"


#: 数据面变异名 → 改真源那一处的动作（`MUTATIONS` 里以 `data:` 开头的锚点查这张表）。
DATA_MUTATORS = {
    "data:basis-index": _basis_index_oob,
    "data:five-no-local": _five_no_local,
    "data:null-out-of-um": _null_out_of_um,
    "data:scored-into-um": _scored_into_um,
    "data:no-rubric-version": _drop_rubric_version,
    "data:basis-quote-broken": _break_referenced_quote,
}


def judge():
    del _red[:]
    TAMPER.clear()
    group_snapshot()
    group_cite()
    group_quote()
    group_basis()
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
    # ---- 数据面变异：锚点以 `data:` 开头，改的是 plugins.json 的**临时副本**（绝不写已提交真源）----
    # 为什么 [A] 组必须配数据面变异：③b 段判的是**真源**里的基座与未测维度。改实现源码会同时
    # 惊动 [S]／[C]／[Q] 组的复算与引文面（复算闸只认 output、引文闸只认 quotes），红项就
    # 不可能「恰好一条」；只有改真源才能做到「只红 [A] 组那一条」。
    # 元组形状与代码面一致（old/new 位给变异名与空串），由 old 以 "data:" 开头区分。
    ("Mn-a", DATA_REL, "data:basis-index", "", {"A15"}),
    ("Mn-b", DATA_REL, "data:five-no-local", "", {"A16"}),
    ("Mn-c", DATA_REL, "data:null-out-of-um", "", {"A17"}),
    ("Mn-d", DATA_REL, "data:no-rubric-version", "", {"A18"}),
    # Mn-e／Mn-f 是按「每条新断言都要有一组数据面变异钉住」补齐的：
    #   Mn-e 让 **A14** 转红（改坏一条被基座引用的证据）；Mn-f 让 **A17 的反方向**转红
    #   （把有分数的维度塞进 unmeasured_dims）。
    ("Mn-e", DATA_REL, "data:basis-quote-broken", "", {"A14"}),
    ("Mn-f", DATA_REL, "data:scored-into-um", "", {"A17"}),
)


def _anchor_preflight():
    """锚点自检：任一**代码面**锚点在当前实现里命中次数 ≠1 → ANCHOR-MISS（退出码 2）。

    数据面变异（锚点以 `data:` 开头）不走这一步——它们改的是真源，不是实现源码。
    """
    src = io.open(os.path.join(ROOT, *CHECK_REL.split("/")), encoding="utf-8").read()
    bad = [(mid, src.count(old)) for mid, _rel, old, _new, _exp in MUTATIONS
           if not str(old).startswith("data:") and src.count(old) != 1]
    if not bad:
        return 0
    for mid, n in bad:
        print("  ANCHOR-MISS %s：锚点命中 %d 次（期望 1）" % (mid, n))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


# 生效条件：kind 为数据面变异名、target 为要改写的真源路径时，把 target 改坏一处。
# 调用方传的必须是**临时副本**（见 `_mutate_mode`）——已提交真源整轮只读。
def _apply_data_mutation(kind, target):
    fn = DATA_MUTATORS.get(kind)
    if fn is None:
        raise ValueError("未知的数据面变异：%s" % kind)
    with io.open(target, encoding="utf-8") as fh:
        doc = json.load(fh)
    fn(doc)
    #: 原子替换：万一写的中途被打断，临时副本也不会变成半截 JSON。
    _write_text_atomic(target, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


# 生效条件：path 为文件路径、text 为完整内容时，先写同目录临时文件再 os.replace 原子替换。
def _write_text_atomic(path, text):
    tmp = path + ".tmp-mutation"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _run_quiet(root, data_src=None):
    """以 `--quiet` 在 root 下重跑本守卫，返回 (红项集合, 实跑断言数)。

    显式传两个环境变量给子进程：
      · `REVIEW_SCRATCH_ROOT` —— 子进程借住父进程的沙箱根，且**不清理**它（清理权在 `_SCRATCH_OWNER`）；
      · `EVIDENCE_DATA_SRC` —— 让子进程的 [A] 组去读**临时真源副本**（数据面变异改的就是它），
        已提交真源全程只读。

    **为什么要读回实跑数**：只看 `RED <id>` 行的话，若某变异让守卫吐完「恰好期望的那些红项」
    之后崩在中途，红项集合仍相等，变异被误判 PASS——判据空转。故子进程回报 `RAN <实跑数>`，
    父进程同时校验。
    """
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1")
    env["REVIEW_SCRATCH_ROOT"] = SCRATCH_ROOT
    if data_src:
        env["EVIDENCE_DATA_SRC"] = data_src
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
    print("!! 定点变异自证：逐条短路一条判据／改坏真源一处，对应断言必须**恰好**转红\n")
    #: 数据面变异用的**临时真源**：内容取自已提交真源，写的却是这份副本。
    #: 每个数据面变异都从头重新拷一份——否则多个变异会累积在同一副本上，
    #: 表的先后顺序变成隐含依赖（兄弟件 `test_review_build.py` 踩过这个坑）。
    data_dir = os.path.join(SCRATCH_ROOT, "data_%s" % RUN_TOKEN)
    os.makedirs(data_dir, exist_ok=True)
    data_tmp = os.path.join(data_dir, "plugins.json")
    shutil.copy(COMMITTED_DATA, data_tmp)
    bad = []
    try:
        base_red, base_ran = _run_quiet(ROOT, data_tmp)
        print("  未变异基线：红项 %s（实跑断言 %d）"
              % (sorted(base_red) or "无（应为无）", base_ran))
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
                if str(old).startswith("data:"):
                    #: 数据面变异一律打在**临时副本**上；沙箱里那份已提交真源不动，
                    #: 故 [S]／[C]／[Q] 组读到的仍是干净数据（红项才不会外溢）。
                    shutil.copy(COMMITTED_DATA, data_tmp)
                    _apply_data_mutation(old, data_tmp)
                else:
                    p = os.path.join(root, *rel.split("/"))
                    t = io.open(p, encoding="utf-8").read()
                    io.open(p, "w", encoding="utf-8", newline="\n").write(
                        t.replace(old, new, 1))
                red, ran = _run_quiet(root, data_tmp)
                hit = (red == set(expect)) and (ran == ASSERT_TOTAL)
                if not hit:
                    bad.append("%s：红项 %s ≠ 期望 %s，或实跑断言数 %d ≠ %d"
                               % (mid, sorted(red), sorted(expect), ran, ASSERT_TOTAL))
                print("  [%s] %s：红项 %d（期望 %d）实跑 %d%s"
                      % ("PASS" if hit else "FAIL", mid, len(red), len(expect), ran,
                         "" if hit else " 实=%s 期=%s" % (sorted(red), sorted(expect))))
            finally:
                shutil.rmtree(root, ignore_errors=True)
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
    print("\n定点变异：%s" % ("PASS（逐条恰好命中期望红项）" if not bad
                              else "FAIL —— " + "；".join(bad)))
    print("通过 %d / 失败 %d（变异 %d 组）"
          % (len(MUTATIONS) - len(bad), len(bad), len(MUTATIONS)))
    return 0 if not bad else 1


#: 断言总数不手写常数：S 组 13 ＋ C 组 5 ＋ Q 组 5 ＋ **A 组 7**（A14–A20）。末行打印**实跑计数**，
#: 与它不等即判红（少跑不许伪装成通过）。`--quiet` 不跳过任何一条，故两处同值。
ASSERT_TOTAL = 13 + 5 + 5 + 7


def main():
    #: `--list` 也必须走下面这个 `try` 的 `finally`：沙箱根是**模块导入时**就建出来的
    #: （`_pick_scratch_root()`），早退路径若在 `try` 之前 `return`，那个目录就永远没人清。
    #: ★ 这只是**一半**原因；另一半在 `_pick_scratch_root()`／`_unique_scratch_dir()`：
    #:   本机 DSH 沙箱下 `tempfile.mkdtemp()` 建出来的目录是废的（子目录建不进去、自己也删不掉），
    #:   于是「探针失败 → 回退工作区」每跑一次都在临时目录里留一个清不掉空壳，而
    #:   `rmtree(..., ignore_errors=True)` 把失败静默咽了下去。两处都已修：改用 `os.makedirs()`
    #:   建沙箱目录（删得干净），并让清理失败**出声**（`_drop_scratch_root()`）。
    try:
        if "--list" in sys.argv:
            for mid, rel, _old, _new, exp in MUTATIONS:
                print("  %s  target=%-28s expect_red=%s" % (mid, rel, sorted(exp)))
            return 0
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
        if _SCRATCH_OWNER and not _drop_scratch_root():
            sys.stderr.write(
                "[警告] 沙箱根清不掉：%s\n"
                "       本机沙箱下「本进程建的目录」可能连创建者自己都删不掉"
                "（环境限制，**不是**判据失败）；该目录已留给人工清理。\n" % SCRATCH_ROOT)


if __name__ == "__main__":
    sys.exit(main())
