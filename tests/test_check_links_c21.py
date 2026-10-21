# -*- coding: utf-8 -*-
"""守卫：check_links.py 的 scheme 大小写必须不敏感（C2-1）。

缺陷：`URL_RE` 无 `IGNORECASE` ⇒ `HTTPS://`/`Https://`/`HtTpS://` 整条不被提取；
G2 用 `url.startswith("https://")` ⇒ 进了守卫层也把大写 https 误判「非 https」。

本守卫走**真实入口 main()**（只关 G4 可达性，不触网），断言退出码与报告条数。
变异驱动按 **nodeid 集合相等** 判定，并额外断言 `rc==1`、输出无 `ERROR` / collection error。

用法：python -X utf8 tests/test_check_links_c21.py
      python -X utf8 tests/test_check_links_c21.py --mutate
退出码：0 全绿；1 有失败；2 变异锚点缺失。
"""
import contextlib
import io
import os
import shutil
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "scripts", "check_links.py")
QUIET = "--quiet" in sys.argv
MUTATE_ONLY = "--mutate" in sys.argv
FX_ROOT = os.path.join(os.path.dirname(ROOT), "_fx")

BASE = ["https://github.com/a/b/issues/1",
        "https://github.com/c/d/pull/2",
        "https://gist.github.com/e/f"]
PH = "example.com/placeholder"


def load():
    """直接编译源码执行，绕开 __pycache__（变异前后同尺寸时旧 .pyc 会复用）。"""
    src = io.open(SCRIPT, encoding="utf-8").read()
    mod = type(sys)("check_links_c21")
    mod.__file__ = SCRIPT
    exec(compile(src, SCRIPT, "exec"), mod.__dict__)
    return mod


def run_main(m, d):
    orig = m.run_guards
    m.run_guards = lambda urls, check_reachability=True: orig(urls, check_reachability=False)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            try:
                rc = m.main([d])
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue()
    finally:
        m.run_guards = orig


def fixture(name, last):
    d = os.path.join(FX_ROOT, name)
    os.makedirs(d, exist_ok=True)
    with io.open(os.path.join(d, "links.md"), "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(BASE + [last]) + "\n")
    return d


def observe(m, name, last):
    rc, out = run_main(m, fixture(name, last))
    fails = [l.strip() for l in out.splitlines() if "FAIL" in l]
    return {
        "rc": rc,
        "n": len(fails),
        "named": last in out,
        "g2": any("G2" in l for l in fails),
    }


EXPECT = {
    "lower": ("https://" + PH, {"rc": 1, "n": 1, "named": True, "g2": False}),
    "upper": ("HTTPS://" + PH, {"rc": 1, "n": 1, "named": True, "g2": False}),
    "mixed": ("Https://" + PH, {"rc": 1, "n": 1, "named": True, "g2": False}),
    "titrecase": ("HtTpS://" + PH, {"rc": 1, "n": 1, "named": True, "g2": False}),
    "http": ("http://" + PH, {"rc": 1, "n": 2, "named": True, "g2": True}),
    "clean": ("https://github.com/x/y/issues/9", {"rc": 0, "n": 0, "named": False, "g2": False}),
}


def change_scope():
    """交付面只许两文件：以 git 工作树改动集为准（worktree 自带全仓，不按文件总数判）。"""
    import subprocess
    r = subprocess.run(["git", "-C", ROOT, "status", "--porcelain"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return ["<not-a-git-worktree>"], []
    changed = set()
    for line in (r.stdout or "").splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        changed.add(path.replace("/", os.sep))
    allowed = {os.path.join("scripts", "check_links.py"),
               os.path.join("tests", "test_check_links_c21.py")}
    return sorted(changed - allowed), sorted(allowed - changed)


def evaluate():
    """返回 {nodeid: bool}；nodeid 为 `<case>.<facet>`，便于集合比较。"""
    m = load()
    res = {}
    for name, (last, exp) in EXPECT.items():
        obs = observe(m, name, last)
        for facet, want in exp.items():
            res["%s.%s" % (name, facet)] = (obs[facet] == want)
    urls_l = m.URL_RE.findall("\n".join(BASE + ["https://" + PH]))
    urls_u = m.URL_RE.findall("\n".join(BASE + ["HTTPS://" + PH]))
    urls_t = m.URL_RE.findall("\n".join(BASE + ["HtTpS://" + PH]))
    res["extract.count"] = len(urls_l) == len(urls_u) == len(urls_t) == 4
    res["extract.casefold"] = [u.lower() for u in urls_l] == [u.lower() for u in urls_u]
    res["extract.ftp-excluded"] = m.URL_RE.findall("ftp://example.com/x") == []
    return res


# ============================================================================
# 预注册：每臂的 EXPECTED 失败 nodeid 集合（**先写死，再跑**；不随后续读数改动）
# 审计要求：预注册集合须独立可读，故从 ARMS 里抽出为模块级常量。
# ============================================================================
EXPECTED_M1 = frozenset({
    "upper.rc", "upper.n", "upper.named",
    "mixed.rc", "mixed.n", "mixed.named",
    "titrecase.rc", "titrecase.n", "titrecase.named",
    "extract.count", "extract.casefold",
})

EXPECTED_M2 = frozenset({
    "upper.n", "upper.g2",
    "mixed.n", "mixed.g2",
    "titrecase.n", "titrecase.g2",
})

EXPECTED = {"M1": EXPECTED_M1, "M2": EXPECTED_M2}

# 两臂（返工单口径）：id → (说明, 原串, 变异串)；期望集见上方预注册常量
ARMS = {
    "M1": ("删 re.IGNORECASE（大写链接不被提取）",
           'URL_RE = re.compile(r"https?://[^\\s\\)\\]\\>\\"\'`，。；：、]+", re.IGNORECASE)',
           'URL_RE = re.compile(r"https?://[^\\s\\)\\]\\>\\"\'`，。；：、]+")'),
    "M2": ("G2 回退成大小写敏感（大写 https 误判非 https）",
           '        if not url.lower().startswith("https://"):',
           '        if not url.startswith("https://"):'),
}


def _looks_like_import_error(out):
    bad = ("Traceback", "ImportError", "ModuleNotFoundError", "collection error",
           "ERROR", "SyntaxError")
    return [b for b in bad if b in out]


def run_guard_subprocess():
    """以子进程跑本守卫（未带 --mutate），取真实退出码与输出。"""
    import subprocess
    r = subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def mutate():
    with io.open(SCRIPT, "rb") as fh:
        orig = fh.read()
    base = evaluate()
    base_red = {n for n, ok in base.items() if not ok}
    if base_red:
        print("[BASE-FAIL] 未变异基线非全绿：%s" % sorted(base_red))
        return 1
    arms_ok = 0
    try:
        for mid in sorted(ARMS):
            desc, old, new = ARMS[mid]
            expected = EXPECTED[mid]
            text = orig.decode("utf-8")
            if text.count(old) != 1:
                print("[ANCHOR-MISS] %s 锚点命中 %d 次（期望 1）" % (mid, text.count(old)))
                return 2
            with io.open(SCRIPT, "wb") as fh:
                fh.write(text.replace(old, new).encode("utf-8"))
            res = evaluate()
            actual = {n for n, ok in res.items() if not ok}
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            rc, out = run_guard_subprocess()
            bad = _looks_like_import_error(out)
            exact = (actual == expected and len(actual) == len(expected)
                     and rc == 1 and not bad)
            if exact:
                arms_ok += 1
            print("[MUTATE-%s] %s rc=%d import-error=%s red=%d expected=%d exact=%s missing=%s extra=%s"
                  % ("OK" if exact else "FAIL", mid, rc, bad,
                     len(actual), len(expected), exact, missing, extra))
    finally:
        with io.open(SCRIPT, "wb") as fh:
            fh.write(orig)
        shutil.rmtree(FX_ROOT, ignore_errors=True)
    print("变异臂：%d 臂 · 集合恰好相等 %d 臂 · nodeid 总数 %d"
          % (len(ARMS), arms_ok, len(evaluate())))
    return 0 if arms_ok == len(ARMS) else 1


def main():
    if MUTATE_ONLY:
        return mutate()
    extra, missing = change_scope()
    res = evaluate()
    #: 只判**越界**（改了不该改的），不判 missing（该改的没改）。
    #: 为什么：missing 判的是「这份交付把两个文件都改了」——那只在**提交该 PR 时**成立；
    #: 一旦合并进 main，工作树干净 ⇒ changed 为空 ⇒ missing 恒等于允许集 ⇒ 本断言
    #: 在 main 上**永远红**（实测自 dfae931 引入起一直红，从没在 main 上绿过）。
    #: 一个只在提交时能过的断言放进常驻守卫，等于让「全量守卫套件」这条门禁永久带一个假红。
    #: 越界判据（extra）在任何时候都有意义：改动集里出现允许集之外的文件就是越界。
    res["tree.change-scope"] = (not extra)
    fail = 0
    for name in sorted(res):
        ok = res[name]
        if not ok:
            fail += 1
        if not QUIET:
            print("  [%s] %s" % ("PASS" if ok else "FAIL", name))
    if extra or missing:
        print("  改动范围越界 extra=%s missing=%s" % (extra, missing))
    print("通过 %d / 失败 %d" % (len(res) - fail, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
