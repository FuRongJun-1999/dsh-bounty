# -*- coding: utf-8 -*-
"""守卫件：cross-eval 守卫的**口径清单同步**（判据数 / 变异数 / 分面守卫登记）。

为什么需要它：`scripts/check_reviews.py` 的判据数、`tests/test_check_reviews.py` 的变异条数
会被**四处文本**复述（守卫自己的 docstring、`bench/cross_eval/README.md`、
`docs/reviews/测评方法论_v0.1.md`、`.github/workflows/review-cross-eval-check.yml`）。
真源加一条判据而文本没跟着改，外部读者就会按旧口径预期覆盖面——这类「口径漂移」本该机械可判。
本件把「声明 == 实测」变成可复算的判据，并给每条判据配一个定点变异自证。

  T1 `--list` 恰好 R1..R14（14 条、无重复、顺序一致）
  T2 守卫 docstring 逐条写出 R1..R14（判据清单不漏项）
  T3 `bench/cross_eval/README.md` 声明的判据数 == 实测，且写出 R13/R14 字样
  T4 方法论声明的判据数 == 实测
  T5 workflow 注释声明的判据数 == 实测
  T6 三处声明的**变异条数**都 == 实测（`tests/test_check_reviews.py` 的 MUTATIONS 条数）
  T7 每条判据都有**专属**定点变异（期望集恰好等于那一条）；R1 只能由「删文件」扇出触发，
     故只要求它在扇出集里出现过——扇出集不能拿来声称「这一条判据有牙」
  T8 四个分面守卫件在库且是 standalone（模块级即跑 ＋ `sys.exit` ＋ 末行「通过 N / 失败 M」）
  T9 四个分面守卫件都登记进 workflow（paths 触发面 ＋ 执行步骤）

用法（standalone：模块级即跑，末行「通过 N / 失败 M」，退出码 0/1；锚点缺失 ⇒ 2）：
  python -X utf8 tests/test_check_reviews_manifest.py            # 断言 ＋ 变异自证
  python -X utf8 tests/test_check_reviews_manifest.py --mutate    # 只跑定点变异面
  python -X utf8 tests/test_check_reviews_manifest.py --quiet     # 只输出 RED <名> ＋ RAN <n>
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

GUARD = "scripts/check_reviews.py"
SELF_TEST = "tests/test_check_reviews.py"
README = "bench/cross_eval/README.md"
METHOD = "docs/reviews/测评方法论_v0.1.md"
WORKFLOW = ".github/workflows/review-cross-eval-check.yml"

#: 分面守卫件（同一守卫按面拆开；必须 standalone、必须登记进 CI 触发面）。
FACE_GUARDS = (
    "tests/test_check_reviews_citation.py",
    "tests/test_check_reviews_sections.py",
    "tests/test_check_reviews_failclosed.py",
    "tests/test_check_reviews_manifest.py",
)

WANT_IDS = ["R%d" % i for i in range(1, 15)]

_pass, _fail, _fails = 0, 0, []


class AnchorMiss(Exception):
    pass


def read(p):
    with io.open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def write(p, t):
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(t)


def sub(path, old, new):
    t = read(path)
    if old not in t:
        raise AnchorMiss("%s 未命中锚点：%r" % (path, old[:60]))
    write(path, t.replace(old, new, 1))


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


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def numbers_in(text, pattern):
    return [int(m) for m in re.findall(pattern, text)]


# ---------------------------------------------------------------- 读数面

def measure(root):
    """把「声明」与「实测」都变成可比较的读数（不判定，只读数——判定在 judge 里）。"""
    m = {}
    p = os.path.join(root, "scripts", "check_reviews.py")
    pr = subprocess.run([sys.executable, "-X", "utf8", p, "--list"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    m["ids"] = [l.strip() for l in (pr.stdout or "").splitlines() if l.strip()]
    gsrc = read(p)
    m["doc_ids"] = re.findall(r"^  (R\d+)\s", gsrc, re.M)

    rp = os.path.join(root, README)
    mp = os.path.join(root, METHOD)
    wp = os.path.join(root, WORKFLOW)
    m["readme"] = read(rp) if os.path.isfile(rp) else ""
    m["method"] = read(mp) if os.path.isfile(mp) else ""
    m["workflow"] = read(wp) if os.path.isfile(wp) else ""
    m["readme_n"] = numbers_in(m["readme"], r"(\d+)\s*条判据")
    m["method_n"] = numbers_in(m["method"], r"(\d+)\s*条判据")
    m["workflow_n"] = numbers_in(m["workflow"], r"(\d+)\s*条判据")
    m["readme_mut"] = numbers_in(m["readme"], r"(\d+)\s*条定点变异")
    m["method_mut"] = numbers_in(m["method"], r"(\d+)\s*条定点变异")
    m["workflow_mut"] = numbers_in(m["workflow"], r"(\d+)\s*条定点变异")

    st = os.path.join(root, SELF_TEST)
    if not os.path.isfile(st):
        raise AnchorMiss("找不到 %s" % st)
    mod = load_module(st, "crev_manifest_selftest")
    muts = getattr(mod, "MUTATIONS", None)
    if not isinstance(muts, dict) or not muts:
        raise AnchorMiss("%s 里没有可读的 MUTATIONS 表" % SELF_TEST)
    m["mut_table"] = muts
    m["mut_n"] = len(muts)
    covered = set()
    singles = set()
    for _k, (expect, _fn) in muts.items():
        covered |= set(expect)
        if len(expect) == 1:
            singles |= set(expect)
    m["covered"] = covered
    m["singles"] = singles

    m["faces"] = {}
    for rel in FACE_GUARDS:
        fp = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(fp):
            m["faces"][rel] = None
            continue
        src = read(fp)
        m["faces"][rel] = {
            "module_level": ("sys.exit(_run())" in src or re.search(r"^sys\.exit\(", src, re.M) is not None),
            "tail": ("通过 %d / 失败 %d" in src),
            "flags": ("--quiet" in src and "--mutate" in src),
            "stdlib": ("import " in src),
            "workflow_registered": (os.path.basename(rel) in m["workflow"]),
            # 只认 `paths:` 块里的那条 YAML 项（文件头注释里也提到同一个 glob，不能算登记）
            "path_glob": ('- "tests/test_check_reviews*.py"' in m["workflow"]),
        }
    return m


def judge(m):
    """按读数判红，返回红项 id 列表（每条判据一个稳定 id）。"""
    red = []
    if m["ids"] != WANT_IDS:
        red.append("T1")
    if m["doc_ids"] != WANT_IDS:
        red.append("T2")
    if not (m["readme_n"] and all(n == len(WANT_IDS) for n in m["readme_n"])
            and "R13" in m["readme"] and "R14" in m["readme"]):
        red.append("T3")
    if not (m["method_n"] and all(n == len(WANT_IDS) for n in m["method_n"])):
        red.append("T4")
    if not (m["workflow_n"] and all(n == len(WANT_IDS) for n in m["workflow_n"])):
        red.append("T5")
    declared = m["readme_mut"] + m["method_mut"] + m["workflow_mut"]
    if not declared or any(n != m["mut_n"] for n in declared):
        red.append("T6")
    # T7 只认**专属**变异（期望集恰好 {某一条判据}）：drop_report/drop_method 那种扇出集
    # 证明的是「文件没了要一起红」，不能拿来声称「这一条判据有牙」。
    # R1（文件齐备）本来就只有「删文件」这一种触发方式，故只要求它在扇出集里出现过。
    dedicated = set(WANT_IDS[1:]) - m["singles"]
    if dedicated or "R1" not in m["covered"]:
        red.append("T7")
    faces_ok = True
    for _rel, f in sorted(m["faces"].items()):
        if not f or not (f["module_level"] and f["tail"] and f["flags"]):
            faces_ok = False
    if not faces_ok:
        red.append("T8")
    reg_ok = True
    for _rel, f in sorted(m["faces"].items()):
        if f is None:
            continue            # 文件缺失由 T8 管，不在 T9 重复计红（避免一因多红）
        if not (f["workflow_registered"] and f["path_glob"]):
            reg_ok = False
    if not reg_ok:
        red.append("T9")
    return red


# ---------------------------------------------------------------- 定点变异

def scratch_copy(root):
    d = tempfile.mkdtemp(prefix="crev-man-")
    for rel in ("scripts", "docs", "bench", "tests", ".github"):
        src = os.path.join(root, *rel.split("/"))
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(d, rel),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return d


def n_readme_count(sb):
    sub(os.path.join(sb, README), "14 条判据", "12 条判据")


def n_method_count(sb):
    sub(os.path.join(sb, METHOD), "（14 条判据", "（12 条判据")


def n_workflow_count(sb):
    sub(os.path.join(sb, WORKFLOW), "（14 条判据）", "（12 条判据）")


def n_docstring_drop_r14(sb):
    p = os.path.join(sb, GUARD)
    lines = read(p).splitlines(True)
    keep = [l for l in lines if not l.startswith("  R14 ")]
    if len(keep) == len(lines):
        raise AnchorMiss("docstring 里没有以 `  R14 ` 开头的判据行")
    write(p, "".join(keep))


def n_drop_one_mutation(sb):
    """删掉一条**不影响覆盖面**的变异（R5 另有两条）⇒ 只该红「条数不一致」。"""
    sub(os.path.join(sb, SELF_TEST),
        '    "cross_engine_reading": ({"R5"}, m_cross_engine_reading),\n', "")


def n_shrink_expectation(sb):
    """把「专属变异恰好一条」的那条判据的期望集改成 R1（条数不变、该判据失去专属覆盖）。

    为什么要动态挑：补上 #372 的八条变异后，R6 等判据已有多条专属变异，随手挑一条改不动覆盖矩阵。
    挑「专属变异恰好一条」的判据才是最小可判红的形式 ⇒ 只该红 T7。
    """
    st = os.path.join(sb, SELF_TEST)
    mod = load_module(st, "crev_manifest_mut")
    counts = {}
    for _k, (expect, _fn) in mod.MUTATIONS.items():
        if len(expect) == 1:
            rid = next(iter(expect))
            counts[rid] = counts.get(rid, 0) + 1
    once = sorted(r for r, n in counts.items() if n == 1 and r != "R1")
    if not once:
        raise AnchorMiss("找不到只有一条专属变异的判据")
    rid = once[0]
    target = None
    for k, (expect, _fn) in mod.MUTATIONS.items():
        if set(expect) == {rid}:
            target = k
            break
    if target is None:
        raise AnchorMiss("找不到 %s 的专属变异" % rid)
    sub(st, '"%s": ({"%s"},' % (target, rid), '"%s": ({"R1"},' % target)


def n_workflow_drop_glob(sb):
    sub(os.path.join(sb, WORKFLOW), '      - "tests/test_check_reviews*.py"\n', "")


def n_drop_face_file(sb):
    os.remove(os.path.join(sb, "tests", "test_check_reviews_sections.py"))


#: (id, 说明, 变异函数, 期望红项集)。期望集必须**恰好**相等。
MUTATIONS = [
    ("N1", "README 判据数 14→12 ⇒ 恰好 T3", n_readme_count, {"T3"}),
    ("N2", "方法论判据数 14→12 ⇒ 恰好 T4", n_method_count, {"T4"}),
    ("N3", "workflow 判据数 14→12 ⇒ 恰好 T5", n_workflow_count, {"T5"}),
    ("N4", "守卫 docstring 删掉 `  R14 ` 判据行 ⇒ 恰好 T2", n_docstring_drop_r14, {"T2"}),
    ("N5", "自证表删掉一条变异（R5 另有覆盖）⇒ 恰好 T6", n_drop_one_mutation, {"T6"}),
    ("N6", "把「专属变异恰好一条」的判据的期望集改成 R1（条数不变，该判据失去专属覆盖）⇒ 恰好 T7",
     n_shrink_expectation, {"T7"}),
    ("N7", "workflow 的 paths 去掉 `tests/test_check_reviews*.py` ⇒ 恰好 T9",
     n_workflow_drop_glob, {"T9"}),
    ("N8", "删掉一个分面守卫件文件 ⇒ 恰好 T8", n_drop_face_file, {"T8"}),
]


def _run():
    if not MUTATE_ONLY:
        m = measure(ROOT)
        red = judge(m)
        check("T1 判据面 `--list` 恰好 R1..R14（14 条、无重复、顺序一致）",
              "T1" not in red, "ids=%s" % m["ids"])
        check("T2 守卫 docstring 逐条写出 R1..R14", "T2" not in red, "doc=%s" % m["doc_ids"])
        check("T3 README 判据数 == 实测 且写出 R13/R14", "T3" not in red,
              "声明=%s 实测=%d" % (m["readme_n"], len(WANT_IDS)))
        check("T4 方法论判据数 == 实测", "T4" not in red,
              "声明=%s 实测=%d" % (m["method_n"], len(WANT_IDS)))
        check("T5 workflow 判据数 == 实测", "T5" not in red,
              "声明=%s 实测=%d" % (m["workflow_n"], len(WANT_IDS)))
        check("T6 三处声明的变异条数都 == 自证表实测条数", "T6" not in red,
              "README=%s 方法论=%s CI=%s 实测=%d"
              % (m["readme_mut"], m["method_mut"], m["workflow_mut"], m["mut_n"]))
        check("T7 每条判据至少被一条定点变异覆盖", "T7" not in red,
              "未覆盖=%s" % sorted(set(WANT_IDS) - m["covered"]))
        check("T8 四个分面守卫件在库且 standalone（模块级即跑/末行格式/双开关）", "T8" not in red,
              "面=%s" % {k: bool(v) for k, v in sorted(m["faces"].items())})
        check("T9 四个分面守卫件都登记进 workflow（paths ＋ 执行步骤）", "T9" not in red,
              "登记=%s" % {k: bool(v and v["workflow_registered"]) for k, v in sorted(m["faces"].items())})

    for mid, desc, fn, expect in MUTATIONS:
        sb = scratch_copy(ROOT)
        try:
            fn(sb)
        except AnchorMiss as e:
            print("ANCHOR-MISS %s" % e)
            return 2
        try:
            got = set(judge(measure(sb)))
        finally:
            shutil.rmtree(sb, ignore_errors=True)
        check("%s 变异：%s" % (mid, desc), got == set(expect),
              "期望=%s 实得=%s" % (sorted(expect), sorted(got)))

    if QUIET:
        for n in _fails:
            print("RED %s" % n)
        print("RAN %d" % (_pass + _fail))
    print("通过 %d / 失败 %d" % (_pass, _fail))
    return 1 if _fail else 0


# 模块级即跑（standalone 守卫件体例：直接被 `python tests/xxx.py` 执行，不经 pytest 收集）。
sys.exit(_run())
