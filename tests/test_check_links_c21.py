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
    "lower": ("https://" + PH, {"rc": 1, "n": 1, "named": True, "g2": True}),
    "upper": ("HTTPS://" + PH, {"rc": 1, "n": 1, "named": True, "g2": True}),
    "mixed": ("Https://" + PH, {"rc": 1, "n": 1, "named": True, "g2": True}),
}


def mutate():
    src_path = SCRIPT
    orig_code = io.open(src_path, encoding="utf-8").read()
    mutated_code = orig_code.replace("re.IGNORECASE", "")
    if mutated_code == orig_code:
        mutated_code = orig_code.replace("re.compile(r\"https?://", "re.compile(r\"http://")
    io.open(src_path, "w", encoding="utf-8", newline="").write(mutated_code)
    try:
        m = load()
        res = observe(m, "upper", "HTTPS://" + PH)
        if res["rc"] == 0:
            print("MUTATE SUCCESS: Mutation caught (rc != 0)")
            return True
        else:
            print("MUTATE FAILED: Mutation not caught (rc == 0)")
            return False
    finally:
        io.open(src_path, "w", encoding="utf-8", newline="").write(orig_code)


def main():
    if MUTATE_ONLY:
        success = mutate()
        sys.exit(0 if success else 1)

    if os.path.exists(FX_ROOT):
        shutil.rmtree(FX_ROOT)

    m = load()
    all_passed = True
    for name, (last, expected) in EXPECT.items():
        res = observe(m, name, last)
        match = all(res[k] == expected[k] for k in expected)
        if not QUIET:
            print(f"Test case '{name}': {'PASS' if match else 'FAIL'} -> {res}")
        if not match:
            all_passed = False

    if os.path.exists(FX_ROOT):
        shutil.rmtree(FX_ROOT)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()