# -*- coding: utf-8 -*-
"""守卫件：`scripts/check_reviews.py` 的**取证面**（R4/R5/R13/R14）判别力自证。

本件把「报告里的读数指不指得到出处」这一面单独钉住，覆盖四条判据：
  R4  引用的 `raw/<文件>` 真实存在。
  R5  围栏里的读数行必须在**该报告自己的证据桶**里逐字可指；跨引擎引用必须在围栏紧邻
      上方点名 `raw/<文件>`；`raw/*.sh` / `raw/*.py` **不是**读数证据面。
  R13 声称出处与证据一致：`raw/<文件>` 引用所在行的标识符型 token 必须真在那份文件里；
      如实写「未落盘」的 token 豁免。
  R14 正文（围栏之外）里的整行复述读数行 / 64 位摘要同样必须逐字可指。

用法（standalone：模块级即跑，末行「通过 N / 失败 M」，退出码 0/1；锚点缺失 ⇒ 2）：
  python -X utf8 tests/test_check_reviews_citation.py            # 断言 ＋ 变异面
  python -X utf8 tests/test_check_reviews_citation.py --mutate    # 只跑定点变异面
  python -X utf8 tests/test_check_reviews_citation.py --quiet     # 只输出 RED <名> ＋ RAN <n>
退出码：0 全绿；1 有失败项；2 变异锚点缺失（ANCHOR-MISS，fail-closed）。
"""
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True   # 守卫不得带写副作用（动态加载被守卫文件时不落 __pycache__）
QUIET = "--quiet" in sys.argv
MUTATE_ONLY = "--mutate" in sys.argv
FENCE = chr(96) * 3
SCHEMES = ["LangGraph_v0.1.md", "LlamaIndex-Workflows_v0.1.md", "txtai-Workflow_v0.1.md"]
FAKE_SHA = "ab" * 32

_pass, _fail, _fails = 0, 0, []


class AnchorMiss(Exception):
    pass


def check(name, ok, detail=""):
    global _pass, _fail
    if ok:
        _pass += 1
    else:
        _fail += 1
        _fails.append(name)
    if not QUIET:
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               "" if ok or not detail else "  ← %s" % detail))


def read(p):
    with io.open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def write(p, t):
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(t)


def report(root, i=0):
    return os.path.join(root, "docs", "reviews", SCHEMES[i])


def raw_dir(root):
    return os.path.join(root, "bench", "cross_eval", "raw")


def scratch_copy(root):
    """只拷判据真正读的树（scripts/docs/bench）——与仓内 tests/test_check_reviews.py 同口径。"""
    d = tempfile.mkdtemp(prefix="crev-cite-")
    for rel in ("scripts", "docs", "bench"):
        src = os.path.join(root, rel)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(d, rel),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return d


def run_guard(root):
    cmd = [sys.executable, "-X", "utf8",
           os.path.join(root, "scripts", "check_reviews.py"), "--root", root, "--quiet"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    out = (p.stdout or "") + (p.stderr or "")
    red = sorted(l.split()[1] for l in (p.stdout or "").splitlines() if l.startswith("RED "))
    return red, p.returncode, out


def guard_mod(root):
    p = os.path.join(root, "scripts", "check_reviews.py")
    spec = importlib.util.spec_from_file_location("crev_cite_guard", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 能力面 → 判据（用于「修前形态」的判别力锚定：缺能力必须**判红并点名判据**，不许裸崩）
CRIT_OF = {
    "evidence_files": "R5/R13（读数归属化：按引擎切证据桶）",
    "EVIDENCE_EXT": "R5（证据面：只有读数证据扩展名算证据）",
    "r13_red": "R13（声称出处与证据一致）",
    "prose_only": "R5/R14（围栏之外＝正文面）",
    "fenced_blocks": "R5/R14（围栏状态机）",
    "section_headings": "R5/R14（标题识别：围栏里的标题不算标题）",
}


def _finish_early():
    """把当前累计结果按体例收尾并退 1（用于修前形态：判红并点名，不裸 AttributeError）。"""
    if QUIET:
        for n in _fails:
            print("RED %s" % n)
        print("RAN %d" % (_pass + _fail))
    print("通过 %d / 失败 %d" % (_pass, _fail))
    raise SystemExit(1)


def bucket_lines(root, engine):
    out = set()
    for fn in sorted(os.listdir(raw_dir(root))):
        if fn.startswith(engine + "_") and fn.endswith((".txt", ".json", ".jsonl")):
            out |= {l.strip() for l in read(os.path.join(raw_dir(root), fn)).splitlines() if l.strip()}
    return out


# ---------------------------------------------------------------- 变异件

def m_cross_engine_reading(root):
    """跨引擎贴条（绕过面①）：baseline 独有的 TRACE 行贴进 txtai 报告围栏，无归因 ⇒ 恰好 R5。"""
    p = report(root, 2)
    own = bucket_lines(root, "txtai")
    foreign = None
    for fn in sorted(os.listdir(raw_dir(root))):
        if not (fn.startswith("baseline_") and fn.endswith(".txt")):
            continue
        for line in read(os.path.join(raw_dir(root), fn)).splitlines():
            s = line.strip()
            if s.startswith("TRACE ") and s not in own:
                foreign = s
                break
        if foreign:
            break
    if foreign is None:
        raise AnchorMiss("找不到「baseline 有、txtai 没有」的 TRACE 行")
    write(p, read(p) + "\n" + FENCE + "\n" + foreign + "\n" + FENCE + "\n")


def m_hash_prefix_reading(root):
    """`# ` 前缀（绕过面②）：伪造读数加注释符曾整类免检 ⇒ 恰好 R5。"""
    p = report(root)
    line = "# SHA %s golden=%s match=True lines=40" % (FAKE_SHA, FAKE_SHA)
    write(p, read(p) + "\n" + FENCE + "\n" + line + "\n" + FENCE + "\n")


def m_prose_invent_reading(root):
    """正文伪造读数行（绕过面③）：R5 只看围栏 ⇒ 恰好 R14。"""
    p = report(root)
    line = "SHA %s golden=%s match=True lines=40" % (FAKE_SHA, FAKE_SHA)
    write(p, read(p) + "\n" + line + "\n")


def m_prose_digest(root):
    """正文**句中**的伪造 64 位摘要（R14(b) 的独立信号）⇒ 恰好 R14。"""
    p = report(root)
    write(p, read(p) + "\n补充：本次运行的产物指纹 %s 已随摘要记录。\n" % FAKE_SHA)


def m_py_source_as_evidence(root):
    """`raw/*.py` 源码行当证据（证据面收窄）⇒ 恰好 R5。"""
    mod = guard_mod(root)
    p = report(root, 2)
    own = bucket_lines(root, "txtai")
    cand = None
    for fn in sorted(os.listdir(raw_dir(root))):
        if not fn.endswith(".py"):
            continue
        for line in read(os.path.join(raw_dir(root), fn)).splitlines():
            s = line.strip()
            if s and s not in own and mod.READING_RE.search(s):
                cand = s
                break
        if cand:
            break
    if cand is None:
        raise AnchorMiss("找不到「raw/*.py 里有、txtai 证据桶里没有」的读数形态行")
    write(p, read(p) + "\n" + FENCE + "\n" + cand + "\n" + FENCE + "\n")


def m_invent_citation(root):
    """R13：声称 `AB_RATIO` 见 `raw/langgraph_runner.txt`，而该 token 只落在 timing_ab 里。"""
    p = report(root)
    t = read(p)
    i = t.index("## 5. 不适用条件")
    add = "\n补充证据：`AB_RATIO` 见 `raw/langgraph_runner.txt`。\n"
    write(p, t[:i] + add + t[i:])


def m_drop_unlanded_declaration(root):
    """删掉 §5 尾部的「证据未落盘」如实声明（= P0-01 的**修前形态**）⇒ 恰好 R13。

    反面证明豁免通道是**真通道**：声明在 ⇒ 未落盘 token 放行；声明删 ⇒ 同一批 token 判红。
    """
    p = report(root)
    lines = read(p).splitlines()
    keep, hit = [], 0
    for ln in lines:
        if "未落盘" in ln and "证据未落盘清单" in ln:
            hit += 1
            continue
        keep.append(ln)
    if hit != 1:
        raise AnchorMiss("找不到唯一的「证据未落盘清单」行（命中 %d）" % hit)
    write(p, "\n".join(keep) + "\n")


def m_fake_raw_ref(root):
    p = report(root)
    write(p, read(p) + "\n见 raw/not_exist_zzz.txt\n")


def m_attributed_foreign_reading(root):
    """**正向**：跨引擎行 ＋ 围栏紧邻上方点名真出处 ⇒ 0 红（归因白名单有效，不是一刀切）。"""
    p = report(root, 2)
    own = bucket_lines(root, "txtai")
    foreign, src = None, None
    for fn in sorted(os.listdir(raw_dir(root))):
        if not (fn.startswith("baseline_") and fn.endswith(".txt")):
            continue
        for line in read(os.path.join(raw_dir(root), fn)).splitlines():
            s = line.strip()
            if s.startswith("TRACE ") and s not in own:
                foreign, src = s, fn
                break
        if foreign:
            break
    if foreign is None:
        raise AnchorMiss("找不到「baseline 有、txtai 没有」的 TRACE 行")
    add = ("\n以下为 `raw/%s` 原文片段：\n\n%s\n%s\n%s\n" % (src, FENCE, foreign, FENCE))
    write(p, read(p) + add)


def m_own_reading_fenced(root):
    """**正向**：本引擎桶里已有的读数行贴进本引擎围栏 ⇒ 0 红（防一刀切）。"""
    p = report(root, 2)
    own = None
    for fn in sorted(os.listdir(raw_dir(root))):
        if fn.startswith("txtai_") and fn.endswith(".txt"):
            for line in read(os.path.join(raw_dir(root), fn)).splitlines():
                s = line.strip()
                if s.startswith("TRACE "):
                    own = s
                    break
        if own:
            break
    if own is None:
        raise AnchorMiss("txtai 桶里没有 TRACE 行")
    write(p, read(p) + "\n" + FENCE + "\n" + own + "\n" + FENCE + "\n")


def m_soft_prefix_legit(root):
    """**正向**：围栏里的合法注释 / 表头 / 分隔线（无读数形态）⇒ 0 红（SOFT_PREFIX 不是整类判红）。"""
    p = report(root, 2)
    block = [FENCE, "# 复跑环境说明（本段只是脚本注释）", "| 项目 | 值 |", "|---|---|",
             "--- 以上为对照表 ---", FENCE, ""]
    write(p, read(p) + "\n" + "\n".join(block))


#: (id, 说明, 变异函数, 期望红项集)。期望集必须**恰好**相等：多红＝语义纠缠，少红＝判据空转。
#: 期望集为空的条目是**正向**面（白名单/免检边界的反面证明：不许一刀切）。
MUTATIONS = [
    ("M1", "跨引擎读数行贴条（无归因）⇒ 恰好 R5", m_cross_engine_reading, {"R5"}),
    ("M2", "`# ` 前缀的伪造读数行 ⇒ 恰好 R5", m_hash_prefix_reading, {"R5"}),
    ("M3", "`raw/*.py` 源码行当证据 ⇒ 恰好 R5", m_py_source_as_evidence, {"R5"}),
    ("M4", "正文伪造读数行（围栏之外）⇒ 恰好 R14", m_prose_invent_reading, {"R14"}),
    ("M5", "正文句中的伪造 64 位摘要 ⇒ 恰好 R14", m_prose_digest, {"R14"}),
    ("M6", "声称出处与证据不符（token 不在所声称文件里）⇒ 恰好 R13", m_invent_citation, {"R13"}),
    ("M7", "删掉「证据未落盘」声明（P0-01 修前形态）⇒ 恰好 R13",
     m_drop_unlanded_declaration, {"R13"}),
    ("M8", "引用了不存在的 raw/<文件> ⇒ 恰好 R4", m_fake_raw_ref, {"R4"}),
    ("M9", "正向：跨引擎行 ＋ 紧邻上方点名真出处 ⇒ 0 红", m_attributed_foreign_reading, set()),
    ("M10", "正向：本引擎桶里的读数行贴进本引擎围栏 ⇒ 0 红", m_own_reading_fenced, set()),
    ("M11", "正向：合法注释/表头/分隔线（无读数形态）⇒ 0 红", m_soft_prefix_legit, set()),
]


def _run():
    d0 = scratch_copy(ROOT)
    try:
        mod = guard_mod(d0)

        # 判别力锚定（修前形态）：实现若未提供本 PR 新增的取证面，必须判红并点名判据，
        # 而不是裸 AttributeError —— 裸崩虽然也非零退出，但不点名＝不合格的守卫。
        need = ("evidence_files", "EVIDENCE_EXT", "r13_red",
                "prose_only", "fenced_blocks", "section_headings")
        missing = [n for n in need if not hasattr(mod, n)]
        if missing:
            for n in missing:
                check("U0 能力面：实现提供 %s（%s）" % (n, CRIT_OF.get(n, "判据面")), False,
                      "缺失（本 PR 新增）⇒ 该判据面不存在")
            _finish_early()

        ev = mod.evidence_files(raw_dir(d0), "txtai")
        check("U1 单元：证据桶按归属切分（只含 txtai_* 的 .txt/.json/.jsonl，不含 .sh/.py）",
              bool(ev) and all(f.startswith("txtai_") and f.endswith(mod.EVIDENCE_EXT) for f in ev),
              "桶=%s" % ev[:4])
        ev_all = mod.evidence_files(raw_dir(d0), None)
        check("U2 单元：engine=None ⇒ 跨引擎并集（方法论用），且严格多于单引擎桶",
              set(ev) < set(ev_all), "并集=%d 单桶=%d" % (len(ev_all), len(ev)))

        raw = raw_dir(d0)
        ok_txt = "见 `AB_RATIO` 于 `raw/langgraph_timing_ab.txt`。"
        bad_txt = "见 `AB_RATIO` 于 `raw/langgraph_runner.txt`。"
        check("U3 单元：R13 对「token 真在所称文件里」放行、对「错配」判红",
              mod.r13_red(ok_txt, raw) is False and mod.r13_red(bad_txt, raw) is True,
              "ok=%s bad=%s" % (mod.r13_red(ok_txt, raw), mod.r13_red(bad_txt, raw)))
        exempt = "以下读数未落盘：`COLD_START_IMPORT_MS` 见 `raw/langgraph_runner.txt`。"
        check("U4 单元：声明「未落盘」的 token 被 R13 豁免（声明不落盘不算编造）",
              mod.r13_red(exempt, raw) is False, "exempt=%s" % mod.r13_red(exempt, raw))
        check("U5 单元：围栏状态机单点——fenced_blocks / prose_only / section_headings 口径一致",
              (mod.prose_only("甲\n" + FENCE + "\n乙\n" + FENCE + "\n丙") == "甲\n丙"
               and mod.fenced_blocks("甲\n" + FENCE + "\n乙\n" + FENCE + "\n丙") == [["乙"]]
               and [h for _i, h in mod.section_headings(FENCE + "\n## 9. 假\n" + FENCE
                                                        + "\n## 1. 真\n")] == ["## 1. 真"]),
              "口径分叉")

        if not MUTATE_ONLY:
            red, rc, _out = run_guard(d0)
            check("F1 正向：真实交付集 0 红", red == [] and rc == 0, "红项=%s rc=%s" % (red, rc))

        for mid, desc, fn, expect in MUTATIONS:
            sb = scratch_copy(ROOT)
            try:
                fn(sb)
            except AnchorMiss as e:
                print("ANCHOR-MISS %s" % e)
                return 2
            try:
                red, rc, out = run_guard(sb)
            finally:
                shutil.rmtree(sb, ignore_errors=True)
            detail = "期望=%s 实得=%s rc=%s" % (sorted(expect), red, rc)
            if set(red) != set(expect):
                note = [l for l in out.splitlines() if l.startswith("NOTE ")]
                if note:
                    detail += "；点名=%s" % "; ".join(note[:2])
            check("%s 变异：%s" % (mid, desc), set(red) == set(expect), detail)
    finally:
        shutil.rmtree(d0, ignore_errors=True)

    if QUIET:
        for n in _fails:
            print("RED %s" % n)
        print("RAN %d" % (_pass + _fail))
    print("通过 %d / 失败 %d" % (_pass, _fail))
    return 1 if _fail else 0


# 模块级即跑（standalone 守卫件体例：直接被 `python tests/xxx.py` 执行，不经 pytest 收集）。
sys.exit(_run())
