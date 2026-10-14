# -*- coding: utf-8 -*-
"""守卫件：`scripts/check_reviews.py` 的**节切分面**（R7/R10/R11/R12）判别力自证。

被测缺陷（已实测）：旧 `section_body()` 用 `text.find(heading)` 取**首次出现**，既不看该字面
是否落在围栏代码块里，也不要求标题唯一，然后按下一个 `^## ` 切尾。后果：
  · 在 §5 正文末尾埋一个假 `## 6. 未测项与原因` ＋ ≥40 字含「未测」的填充，把**真** §6
    清空成「无。」⇒ 守卫 `RED=[] rc=0`（R10 切到假头后面的填充段，真未测节无人看）；
  · 同族：真 §5 清空、真 §2 复跑命令清空、围栏内假头、标题重复 —— R7/R10/R11/R12 全线受影响。
改后：节切分走 `section_body_ex()`（只认**正文区**里逐字相等且唯一的那一节，切尾边界也只在
正文区里找），标题 0 次或 ≥2 次 ⇒ 判红并在 `--quiet` 下打 `NOTE` 点名。

★ 与 #372 的关系（**合并判断，耦合已消除**）：P0-01 原本把「证据未落盘清单」放在 §5 末尾，
于是「清空 §5」会连带删掉该声明、同时打红 R11 与 R13——两个缺陷叠在一条变异上。统一版把
**机器可读的 token 清单**移到 §4（读数明细）末尾，§5 只留一句不含 token 的落盘边界说明，
故 M9（真 §5 清空）现在**恰好**只打红 R11。清单被删的情形由
`tests/test_check_reviews_citation.py` 的 `drop_unlanded_declaration ⇒ {R13}` 单列覆盖。

用法（standalone：模块级即跑，末行「通过 N / 失败 M」，退出码 0/1；锚点缺失 ⇒ 2）：
  python -X utf8 tests/test_check_reviews_sections.py            # 单元面 ＋ 正向 ＋ 变异面
  python -X utf8 tests/test_check_reviews_sections.py --mutate    # 只跑定点变异面
  python -X utf8 tests/test_check_reviews_sections.py --quiet     # 只输出 RED <名> ＋ RAN <n>
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
SCHEME = "LangGraph_v0.1.md"

H0 = "## 0. 结论摘要"
H1 = "## 1. 被测对象与版本"
H2 = "## 2. 复现步骤"
H5 = "## 5. 不适用条件"
H6 = "## 6. 未测项与原因"

#: 填充段：≥40 字、含「未测」（§6 语境）、不含判官词、不含 raw/<文件>.<扩展名> 引用。
FILL6 = ("本节为占位说明：未测项已在各引擎报告的第 6 节与原始读数里披露，"
         "此处不再重复列出，详细原因与边界见对应原始文件。")
FILL5 = ("本节为占位说明：上述不适用条件只覆盖本地单机负载，不涉及网络、凭据、厂商托管服务"
         "与分布式持久化后端，跨进程恢复也不在本轮范围内。")
FILL0 = "本节为占位说明：结论摘要的逐项引用与读数编号已在正文给出，此处不再重复列出。"
CMD2 = ("python3 -X utf8 bench/cross_eval/harness/runner.py "
        "--impl bench/cross_eval/systems/langgraph_impl.py --name langgraph "
        "--modes normal,resume,retry,sequential,parallel")
FILL2 = ("本节为占位说明：复跑命令与依赖安装在下文 §2.3 逐字给出，可直接照抄执行，"
         "不需要任何 LLM/API 凭据。\n" + CMD2)

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


def report_of(root):
    return os.path.join(root, "docs", "reviews", SCHEME)


def scratch_copy(root):
    d = tempfile.mkdtemp(prefix="crev-sec-")
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
    red = sorted(l.split()[1] for l in (p.stdout or "").splitlines() if l.startswith("RED "))
    notes = [l for l in (p.stdout or "").splitlines() if l.startswith("NOTE ")]
    return red, p.returncode, notes


def guard_mod(root):
    p = os.path.join(root, "scripts", "check_reviews.py")
    spec = importlib.util.spec_from_file_location("crev_sec_guard", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 能力面 → 判据（用于「修前形态」的判别力锚定：缺能力必须**判红并点名判据**，不许裸崩）
CRIT_OF = {
    "section_body_ex": "R7/R10/R11/R12（结构化切段：唯一标题 ＋ 围栏状态机）",
    "section_headings": "R5/R14（标题识别：围栏里的标题不算标题）",
    "fenced_blocks": "R5/R14（围栏状态机单点）",
    "prose_only": "R5/R14（围栏之外＝正文面）",
}


def _finish_early():
    """把当前累计结果按体例收尾并退 1（用于修前形态：判红并点名，不裸 AttributeError）。"""
    if QUIET:
        for n in _fails:
            print("RED %s" % n)
        print("RAN %d" % (_pass + _fail))
    print("通过 %d / 失败 %d" % (_pass, _fail))
    raise SystemExit(1)


# ---------------------------------------------------------------- 变异助手

def section_span(t, heading):
    """与**旧实现**同口径的切段（只用来定位「真节」的起止，供变异构造）。"""
    i = t.index(heading)
    m = re.search(r"^## ", t[i + len(heading):], re.M)
    j = i + len(heading) + m.start() if m else len(t)
    return i, j


def empty_section(t, heading, body="无。"):
    i, j = section_span(t, heading)
    return t[:i] + heading + "\n" + body + "\n\n" + t[j:]


def inject_before(t, heading, filler, fenced=False, fake_heading=None):
    i = t.index(heading)
    fh = fake_heading if fake_heading is not None else heading
    if fenced:
        fake = FENCE + "\n" + fh + "\n" + filler + "\n" + FENCE + "\n\n"
    else:
        fake = fh + "\n" + filler + "\n\n"
    return t[:i] + fake + t[i:]


def strip_runner_cmd(t, heading):
    i, j = section_span(t, heading)
    seg, n = re.subn(r"^python3 -X utf8 .*runner\.py.*$",
                     "# （本变异已把真 §2 的复跑命令删掉）", t[i:j], flags=re.M)
    if n == 0:
        raise AnchorMiss("真 %s 里没有可删的复跑命令行" % heading)
    return t[:i] + seg + t[j:]


def m_fake_section6(root, filler=FILL6, fenced=False):
    p = report_of(root)
    t = empty_section(read(p), H6)
    write(p, inject_before(t, H6, filler, fenced=fenced))


def m_fake_section2(root, fenced=False):
    p = report_of(root)
    t = strip_runner_cmd(read(p), H2)
    write(p, inject_before(t, H2, FILL2, fenced=fenced))


def m_dup_section(root, heading, filler):
    p = report_of(root)
    write(p, inject_before(read(p), heading, filler))


def m_dup_section0(root):
    """假 §0 头埋在 §0 正文末尾（真 §0 的结论条目完好）⇒ 重复标题 ⇒ 恰好 R12。"""
    p = report_of(root)
    write(p, inject_before(read(p), H1, FILL0, fake_heading=H0))


def m_empty_section(root, heading):
    p = report_of(root)
    write(p, empty_section(read(p), heading))


#: (id, 说明, 变异函数, 期望红项集, 期望 NOTE 子串或 None)。期望集必须**恰好**相等。
MUTATIONS = [
    ("M1", "假 §6 头 ＋ ≥40 字含「未测」填充 ＋ 真 §6 清空「无。」",
     lambda sb: m_fake_section6(sb), {"R10"}, ("R10", "重复")),
    ("M2", "围栏内假 §6 头 ＋ 围栏内填充 ＋ 真 §6 清空「无。」（假头不算标题 ⇒ 按**空节**判红，无 NOTE）",
     lambda sb: m_fake_section6(sb, fenced=True), {"R10"}, None),
    ("M3", "标题重复：§6 头出现 2 次（真 §6 内容完好）",
     lambda sb: m_dup_section(sb, H6, FILL6), {"R10"}, ("R10", "重复")),
    ("M4", "标题重复：§5 头出现 2 次（真 §5 与「未落盘」声明完好）",
     lambda sb: m_dup_section(sb, H5, FILL5), {"R11"}, ("R11", "重复")),
    ("M5", "标题重复：§2 头出现 2 次（真 §2 命令完好）",
     lambda sb: m_dup_section(sb, H2, FILL2), {"R7"}, ("R7", "重复")),
    ("M6", "标题重复：假 §0 头埋在 §0 正文末尾（真 §0 结论条目完好）",
     m_dup_section0, {"R12"}, ("R12", "重复")),
    ("M7", "真 §6 清空「无。」（无假头，旧实现也红）",
     lambda sb: m_empty_section(sb, H6), {"R10"}, None),
    ("M8", "真 §2 的复跑命令被删（假头不在场）",
     lambda sb: write(report_of(sb), strip_runner_cmd(read(report_of(sb)), H2)), {"R7"}, None),
    ("M9", "真 §5 清空「无。」（清单已移到 §4 末尾，故不再连带 R13）",
     lambda sb: m_empty_section(sb, H5), {"R11"}, None),
    ("M10", "围栏内假 §2 头 ＋ 围栏内含命令填充 ＋ 真 §2 命令清空",
     lambda sb: m_fake_section2(sb, fenced=True), {"R7"}, None),
]

DOC_UNIQUE = "# 头\n\n## 1. 甲\n甲正文\n\n## 2. 乙\n乙正文\n\n## 3. 丙\n丙正文\n"
DOC_FENCED_HEAD = ("## 1. 甲\n甲正文\n\n" + FENCE + "\n## 2. 乙\n假正文\n" + FENCE
                   + "\n\n## 2. 乙\n真正文\n\n## 3. 丙\n丙正文\n")
DOC_DUP = "## 1. 甲\n甲正文\n\n## 2. 乙\n乙正文一\n\n## 2. 乙\n乙正文二\n\n## 3. 丙\n丙正文\n"
DOC_FENCE_BOUNDARY = ("## 2. 乙\n起\n" + FENCE + "\n## 9. 庚\n围栏内样例\n" + FENCE
                      + "\n止\n\n## 3. 丙\n丙正文\n")


def _run():
    d0 = scratch_copy(ROOT)
    try:
        mod = guard_mod(d0)

        # 判别力锚定（修前形态）：实现若未提供结构化切段面，必须判红并点名判据，
        # 而不是裸 AttributeError —— 裸崩虽然也非零退出，但不点名＝不合格的守卫。
        need = ("section_body_ex", "section_headings", "fenced_blocks", "prose_only")
        missing = [n for n in need if not hasattr(mod, n)]
        if missing:
            for n in missing:
                check("U0 能力面：实现提供 %s（%s）" % (n, CRIT_OF.get(n, "判据面")), False,
                      "缺失（本 PR 新增）⇒ 该判据面不存在")
            _finish_early()

        body, why = mod.section_body_ex(DOC_UNIQUE, "## 2. 乙")
        check("U1 单元：唯一标题 ⇒ 恰好取到该节正文（无点名）",
              body.strip() == "乙正文" and not why, "正文=%r why=%r" % (body.strip()[:20], why))
        body, why = mod.section_body_ex(DOC_FENCED_HEAD, "## 2. 乙")
        check("U2 单元：围栏里的同名标题**不算**标题（取正文区那一节）",
              body.strip() == "真正文" and not why, "正文=%r why=%r" % (body.strip()[:20], why))
        body, why = mod.section_body_ex(DOC_UNIQUE, "## 7. 辛")
        check("U3 单元：标题 0 次 ⇒ (None, 含「缺失」的点名)", body is None and "缺失" in (why or ""),
              "why=%r" % why)
        body, why = mod.section_body_ex(DOC_DUP, "## 2. 乙")
        check("U4 单元：标题 ≥2 次 ⇒ (None, 含「重复」的点名)", body is None and "重复" in (why or ""),
              "why=%r" % why)
        body, _why = mod.section_body_ex(DOC_FENCE_BOUNDARY, "## 2. 乙")
        check("U5 单元：围栏里的 `## ` 不当节边界（样例内容留在正文里）",
              ("围栏内样例" in body and "止" in body and "丙正文" not in body), "正文=%r" % body)
        heads = [h for _i, h in mod.section_headings(DOC_FENCE_BOUNDARY)]
        check("U6 单元：围栏内标题被 section_headings/prose_only 一致排除",
              "## 9. 庚" not in heads and "## 9. 庚" not in mod.prose_only(DOC_FENCE_BOUNDARY),
              "heads=%s" % heads)
        src = read(os.path.join(d0, "scripts", "check_reviews.py"))
        uses = len(re.findall(r"\bscan_lines\(", src))
        check("U7 静态：围栏状态机单点——scan_lines() 唯一实现、三处共用",
              uses >= 4 and all(hasattr(mod, n) for n in ("fenced_blocks", "prose_only",
                                                          "section_body_ex", "section_headings")),
              "scan_lines( 用量=%d" % uses)
        check("U8 单元：section_body() 薄壳——缺失/重复 ⇒ None（旧签名兼容）",
              mod.section_body(DOC_UNIQUE, "## 2. 乙").strip() == "乙正文"
              and mod.section_body(DOC_DUP, "## 2. 乙") is None
              and mod.section_body(DOC_UNIQUE, "## 7. 辛") is None, "薄壳口径分叉")

        if not MUTATE_ONLY:
            red, rc, _n = run_guard(d0)
            check("F1 正向：真实交付集 0 红", red == [] and rc == 0, "红项=%s rc=%s" % (red, rc))

        for mid, desc, fn, expect, note_spec in MUTATIONS:
            sb = scratch_copy(ROOT)
            try:
                fn(sb)
            except AnchorMiss as e:
                print("ANCHOR-MISS %s" % e)
                return 2
            try:
                red, rc, notes = run_guard(sb)
            finally:
                shutil.rmtree(sb, ignore_errors=True)
            check("%s 变异：%s ⇒ 恰好 %s" % (mid, desc, ",".join(sorted(expect))),
                  set(red) == set(expect), "期望=%s 实得=%s rc=%s" % (sorted(expect), red, rc))
            if note_spec:
                rid, word = note_spec
                hit = [n for n in notes if n.startswith("NOTE %s " % rid) and word in n]
                check("%s 点名：结构缺陷须打出 NOTE %s（含「%s」）" % (mid, rid, word),
                      bool(hit), "NOTE 行=%s" % notes)
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
