# -*- coding: utf-8 -*-
"""守卫：bounty_list.validate 对 `score` 的类型/有限性必须 fail-closed 点名（rc=2）。

缺陷（R2-1）：
  1. 只比 `score` 值不等，随后 `%d` 格式化 ⇒ `"3"`/None/list 抛 TypeError 裸栈；
  2. NaN/Infinity/-Infinity 是 float 实例，能过类型判据，但 `%d` 格式化分别抛
     ValueError / OverflowError（`json.loads` 默认接受这三个非标准字面量）。

本守卫断言：rc==2、输出无 Traceback/ValueError/OverflowError、错误串点名、
errs 恰好 +1；并保留既有行为（int/float/bool 通过、漂移仍 rc1）。

用法：python -X utf8 tests/test_bounty_list_score_type.py
      python -X utf8 tests/test_bounty_list_score_type.py --mutate
退出码：0 全绿；1 有失败；2 变异锚点缺失。
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "scripts", "bounty_list.py")
QUIET = "--quiet" in sys.argv
MUTATE_ONLY = "--mutate" in sys.argv


def _workdir():
    try:
        d = tempfile.mkdtemp(prefix="r2-1-")
        probe = os.path.join(d, ".probe")
        with io.open(probe, "w", encoding="utf-8") as fh:
            fh.write("x")
        os.unlink(probe)
        return d
    except OSError:
        d = os.path.join(ROOT, ".r2_tmp")
        os.makedirs(d, exist_ok=True)
        return d


def _load():
    """直接编译源码执行，**绕开 __pycache__**。

    变异前后文件同尺寸时，mtime 粒度可能让旧 .pyc 继续生效，
    导致「变异没生效却显示红/绿」的假读数（本文件曾踩过）。
    """
    src = io.open(SCRIPT, encoding="utf-8").read()
    mod = type(sys)("bounty_list_score_type")
    mod.__file__ = SCRIPT
    exec(compile(src, SCRIPT, "exec"), mod.__dict__)
    return mod


def _real_doc():
    d = os.path.join(ROOT, "docs", "bounty")
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if name.endswith(".json") and os.path.getsize(p) == 29152:
            return json.load(io.open(p, encoding="utf-8"))
    raise RuntimeError("real bounty source json not found")


def _doc(score, difficulty="easy"):
    doc = json.loads(json.dumps(_real_doc()))
    doc["items"][0]["difficulty"] = difficulty
    doc["items"][0]["score"] = score
    return doc


def _run_main(m, d, doc, argv):
    src = os.path.join(d, "src.json")
    io.open(src, "w", encoding="utf-8", newline="").write(json.dumps(doc, ensure_ascii=False))
    m.SRC = src
    m.OUT = os.path.join(d, "out.md")
    err, out = io.StringIO(), io.StringIO()
    old_e, old_o = sys.stderr, sys.stdout
    sys.stderr, sys.stdout = err, out
    try:
        return m.main(argv), err.getvalue()
    except Exception as exc:
        return "EXC:%s" % type(exc).__name__, err.getvalue()
    finally:
        sys.stderr, sys.stdout = old_e, old_o


def _asserts():
    """返回 [(name, ok, detail)]。"""
    m = _load()
    d = _workdir()
    out = []
    try:
        rc, err = _run_main(m, d, _doc(1), ["--stdout"])
        out.append(("valid-int-rc0", rc == 0, "rc=%s" % rc))

        # ---- 类型面（4 形态）----
        for tag, sc, needle in [
            ("str-'3'", "3", "score 类型非法"),
            ("str-'abc'", "abc", "score 类型非法"),
            ("none", None, "NoneType"),
            ("list", [], "list"),
        ]:
            rc, err = _run_main(m, d, _doc(sc), ["--stdout"])
            out.append(("type-%s-rc2" % tag, rc == 2, "rc=%s" % rc))
            out.append(("type-%s-named" % tag,
                        needle in err and "eval-site" in err,
                        err.strip().splitlines()[-1:] or ""))

        # ---- 有限性面（3 形态）：rc2 + 无裸栈 + 点名 + errs 恰好 1 条 ----
        for tag, sc in [("nan", float("nan")), ("inf", float("inf")), ("-inf", float("-inf"))]:
            rc, err = _run_main(m, d, _doc(sc), ["--stdout"])
            clean = (not str(rc).startswith("EXC:")
                     and "Traceback" not in err and "ValueError" not in err
                     and "OverflowError" not in err)
            named = "非有限值" in err and "eval-site" in err
            errs = [l for l in err.splitlines() if l.strip().startswith("- ")]
            out.append(("finite-%s-rc2" % tag, rc == 2, "rc=%s" % rc))
            out.append(("finite-%s-no-traceback" % tag, clean, err.strip()[-80:]))
            out.append(("finite-%s-named" % tag, named, err.strip().splitlines()[-1:] or ""))
            out.append(("finite-%s-errs-1" % tag, len(errs) == 1, "errs=%d" % len(errs)))

        # ---- 既有行为保持 ----
        for tag, sc in [("float", 1.0), ("bool", True)]:
            rc, _ = _run_main(m, d, _doc(sc), ["--stdout"])
            out.append(("numeric-%s-rc0" % tag, rc == 0, "rc=%s" % rc))
        # ---- 渲染层兜底：绕过 validate 直接 render，NaN 也不得裸栈 ----
        for tag, sc in [("nan", float("nan")), ("inf", float("inf")),
                        ("-inf", float("-inf"))]:
            try:
                text = m.render(_doc(sc))
                ok = "nan" in text.lower() or "inf" in text.lower()
                out.append(("render-%s-no-raise" % tag, ok, "len=%d" % len(text)))
            except Exception as exc:
                out.append(("render-%s-no-raise" % tag, False,
                            "%s: %s" % (type(exc).__name__, exc)))
        io.open(os.path.join(d, "out.md"), "w", encoding="utf-8", newline="").write("stale")
        rc, err = _run_main(m, d, _doc(1), ["--check"])
        out.append(("drift-rc1", rc == 1, "rc=%s err=%r" % (rc, err.strip()[:60])))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


TYPE_BLOCK = ("        elif not isinstance(it.get(\"score\"), (int, float)):\n"
              "            # ★本笔：**score 类型判据**。旧实现只比值不等，然后 `%d` 格式化：\n"
              "            # 真源里 `\"score\": \"3\"`（合法 JSON 的非法类型）会抛\n"
              "            # `TypeError: %d format: a real number is required, not str` —— 裸栈冒到\n"
              "            # `main()`，退出码退化成 1，与「产物漂移」撞码；而本函数契约是\n"
              "            # fail-closed 点名、由 `main()` 统一退 2。bool/float 是数值等价，保留通过。\n"
              "            errs.append(\"%s score 类型非法：%r（%s），应为数值\"\n"
              "                        % (i, it.get(\"score\"), type(it.get(\"score\")).__name__))\n")

FINITE_BLOCK = ("        elif not math.isfinite(it.get(\"score\")):\n"
                "            # ★本笔：**score 有限性判据**。NaN/Infinity/-Infinity 都是 float 实例，\n"
                "            # 能过上面的 isinstance；随后 `%d` 格式化分别抛 ValueError / OverflowError\n"
                "            # （`json.loads` 默认接受这三个非标准字面量，故真源里可出现）。\n"
                "            # 与类型判据同路：进 errs 聚合、由 main() 统一退 2，绝不裸栈。\n"
                "            errs.append(\"%s score 非有限值：%r，应为有限数值\"\n"
                "                        % (i, it.get(\"score\")))\n")

VALUE_BLOCK = ("        elif it.get(\"score\") != DIFFICULTY_SCORES[d]:\n"
               "            errs.append(\"%s 分与难度不符：%s→%r 表值 %r\"\n"
               "                        % (i, d, it.get(\"score\"), DIFFICULTY_SCORES[d]))\n")

# 臂：id → (说明, 原串, 变异串, 期望红项谓词)
ARMS = {
    "M1": ("删类型判据（回退到裸 %d）", TYPE_BLOCK, "",
           lambda n: n.startswith("type-") and (n.endswith("-rc2") or n.endswith("-named"))),
    "M2": ("删有限性判据（NaN/Inf 被误报成值不符）", FINITE_BLOCK, "",
           lambda n: n.startswith("finite-") and n.endswith("-named")),
    "M3": ("有限性判据错误串回退 %d（NaN/Inf 裸栈）",
           FINITE_BLOCK,
           ("        elif not math.isfinite(it.get(\"score\")):\n"
            "            # ★本笔：**score 有限性判据**。NaN/Infinity/-Infinity 都是 float 实例，\n"
            "            # 能过上面的 isinstance；随后 `%d` 格式化分别抛 ValueError / OverflowError\n"
            "            # （`json.loads` 默认接受这三个非标准字面量，故真源里可出现）。\n"
            "            # 与类型判据同路：进 errs 聚合、由 main() 统一退 2，绝不裸栈。\n"
            "            errs.append(\"%s score 非有限值：%d，应为有限数值\"\n"
            "                        % (i, it.get(\"score\")))\n"),
           lambda n: n.startswith("finite-")),
    "M4": ("渲染层回退 %d（绕过 validate 时 NaN/Inf 裸栈）",
           "        L.append(\"| %s | [%s](#%s) | %s | %r | %s | %s |\" % (",
           "        L.append(\"| %s | [%s](#%s) | %s | %d | %s | %s |\" % (",
           lambda n: n.startswith("render-")),
}


def _mutate():
    with io.open(SCRIPT, "rb") as fh:
        orig = fh.read()
    arms_ok = 0
    killed = {}
    try:
        for mid in sorted(ARMS):
            desc, old, new, expect = ARMS[mid]
            text = orig.decode("utf-8")
            if text.count(old) != 1:
                print("[ANCHOR-MISS] %s 锚点命中 %d 次（期望 1）" % (mid, text.count(old)))
                return 2
            with io.open(SCRIPT, "wb") as fh:
                fh.write(text.replace(old, new).encode("utf-8"))
            res = _asserts()
            red = [n for n, ok, _ in res if not ok]
            want = [n for n, _, _ in res if expect(n)]
            exact = set(red) == set(want)
            if exact:
                arms_ok += 1
            killed[mid] = red
            print("[MUTATE-%s] arms=%s killed=%d names=%s exact=%s"
                  % ("OK" if exact else "FAIL", mid, len(red), red, exact))
        print("变异臂：%d 臂 · 恰好点红 %d 臂 · 断言总数 %d"
              % (len(ARMS), arms_ok, len(_asserts())))
    finally:
        with io.open(SCRIPT, "wb") as fh:
            fh.write(orig)
    return 0 if arms_ok == len(ARMS) else 1


def main():
    if MUTATE_ONLY:
        return _mutate()
    res = _asserts()
    fail = 0
    for name, ok, detail in res:
        if not ok:
            fail += 1
        if not QUIET:
            print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                                   "" if ok else "  ← %s" % (detail,)))
    print("通过 %d / 失败 %d" % (len(res) - fail, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
