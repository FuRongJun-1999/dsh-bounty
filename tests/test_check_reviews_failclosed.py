# -*- coding: utf-8 -*-
"""守卫件：**失败与缺字段不许判通过**（R8 fail-closed ＋ runner 的失败语义）。

两半，各自独立取证：
  A · 守卫侧（`scripts/check_reviews.py` 的 R8）
      旧版把「模式记录缺 sha256 / `matches_golden` 非布尔」用 `continue` **静默放行**
      ⇒ 未披露的不一致被算成好成绩。改后这些一律判红，唯一放行通道是报告里**同一行**
      显式声明该模式「未产出/无指纹/未落盘」；`matches_golden=false` 则必须**同一行**披露不一致。
      「modes 整个缺失 / 一个记录都没有」同样判红（没记录 ≠ 没不一致）。
  B · 运行器侧（`bench/cross_eval/harness/runner.py`）
      旧版 `main()` 无 `sys.exit` ⇒ 五个模式全异常仍 EXIT=0；只搬 6 个白名单证据键 ⇒
      引擎自报的其余键（steps_reused_from_checkpoint / counts_* / workers / results）静默丢弃；
      `cfg_for` 的 `mode` 形参零引用 ⇒ cfg 里恒无档位。改后：失败非零退出 ＋ 结论字段
      （`conclusion`）＋ 证据键**全量**搬运（不可序列化键记名 `dropped_keys`）＋ `cfg["mode"]`。
      这一半**真跑** runner.py（纯标准库、不联网、临时目录落盘），不是读源码猜。

用法（standalone：模块级即跑，末行「通过 N / 失败 M」，退出码 0/1；锚点缺失 ⇒ 2）：
  python -X utf8 tests/test_check_reviews_failclosed.py            # 断言 ＋ 变异面
  python -X utf8 tests/test_check_reviews_failclosed.py --mutate    # 只跑定点变异面
  python -X utf8 tests/test_check_reviews_failclosed.py --quiet     # 只输出 RED <名> ＋ RAN <n>
退出码：0 全绿；1 有失败项；2 变异锚点缺失（ANCHOR-MISS，fail-closed）。
"""
import io
import json
import os
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

#: 假的被测实现：覆盖「正常 / 抛异常 / 自报 ok=False / 不可序列化证据键」四种面。
FAKE_IMPL = '''# -*- coding: utf-8 -*-
NAME = "fake"
CAPS = {"retry": False}


class NotSerializable(object):
    def __repr__(self):
        return "<not-serializable>"


def run(mode, cfg):
    if mode == "boom":
        raise RuntimeError("injected failure in %s" % mode)
    if mode == "ng":
        return {"ok": False, "note": "self-reported not ok", "cfg_mode": cfg.get("mode")}
    return {"ok": True, "trace": ["load", "emit"], "attempts": 1,
            "custom_evidence_key": {"nested": [1, 2]},
            "unserializable": NotSerializable(),
            "cfg_mode": cfg.get("mode")}
'''

FAKE_IMPL_WRITES = '''# -*- coding: utf-8 -*-
"""对照件：run() 写出产物文件 ⇒ 走 runner 的 sha256/matches_golden 分支。"""
import os

NAME = "fakew"
CAPS = {}


def run(mode, cfg):
    with open(cfg["out"], "w", encoding="utf-8", newline="\\n") as f:
        f.write("x\\n")
    return {"ok": True, "cfg_mode": cfg.get("mode")}
'''


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


def summary_path(root, name="langgraph"):
    return os.path.join(root, "bench", "cross_eval", "raw", "%s_summary.json" % name)


def scratch_copy(root):
    """只拷判据真正读的树（scripts/docs/bench）——与仓内 tests/test_check_reviews.py 同口径。"""
    d = tempfile.mkdtemp(prefix="crev-fc-")
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
    return red, p.returncode


def run_runner(sandbox, tmp, mods, impl="fake_impl.py", name="fake"):
    """真跑 runner.py（子进程），返回 (rc, 合并输出, rawdir)。"""
    rawdir = os.path.join(tmp, "raw_%s" % name)
    cmd = [sys.executable, "-B", "-X", "utf8",
           os.path.join(sandbox, "bench", "cross_eval", "harness", "runner.py"),
           "--impl", os.path.join(tmp, impl), "--name", name,
           "--modes", mods, "--skip-timing", "--rawdir", rawdir]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return p.returncode, (p.stdout or "") + (p.stderr or ""), rawdir


# ---------------------------------------------------------------- A 面变异（R8）

def _langgraph_modes(root):
    p = summary_path(root)
    d = json.loads(read(p))
    modes = d.get("modes") or {}
    if not modes:
        raise AnchorMiss("summary 里没有 modes")
    return p, d, modes


def m_drop_sha256(root):
    p, d, modes = _langgraph_modes(root)
    k = sorted(modes)[0]
    if "sha256" not in modes[k]:
        raise AnchorMiss("模式 %s 本来就没有 sha256" % k)
    del modes[k]["sha256"]
    write(p, json.dumps(d, ensure_ascii=False, indent=2))


def m_mismatch_silent(root):
    p, d, modes = _langgraph_modes(root)
    k = sorted(modes)[0]
    modes[k]["matches_golden"] = False
    write(p, json.dumps(d, ensure_ascii=False, indent=2))
    pat = ".*\\b%s\\b.*(?:不一致|match=False|matches_golden[^\\n]*False).*" % k
    import re as _re
    if _re.search(pat, read(report(root)), _re.M):
        raise AnchorMiss("报告已披露 %s 不一致" % k)


def m_nonbool_flag(root):
    p, d, modes = _langgraph_modes(root)
    k = sorted(modes)[0]
    modes[k]["matches_golden"] = "false"
    write(p, json.dumps(d, ensure_ascii=False, indent=2))


def m_drop_modes(root):
    p, d, modes = _langgraph_modes(root)
    del d["modes"]
    write(p, json.dumps(d, ensure_ascii=False, indent=2))


def m_record_not_object(root):
    p, d, modes = _langgraph_modes(root)
    k = sorted(modes)[0]
    modes[k] = "ok"
    write(p, json.dumps(d, ensure_ascii=False, indent=2))


def m_broken_summary(root):
    write(summary_path(root), "{ this is not json")


def m_missing_declared(root):
    """**正向**：删掉 sha256，但报告同一行声明该模式未产出指纹 ⇒ 0 红（放行通道有效）。"""
    p, d, modes = _langgraph_modes(root)
    k = sorted(modes)[0]
    del modes[k]["sha256"]
    write(p, json.dumps(d, ensure_ascii=False, indent=2))
    rp = report(root)
    write(rp, read(rp) + "\n补充披露：模式 %s 未产出指纹（本次未落盘）。\n" % k)


def m_mismatch_disclosed(root):
    """**正向**：`matches_golden=false` 且报告同一行披露 ⇒ 0 红。"""
    p, d, modes = _langgraph_modes(root)
    k = sorted(modes)[0]
    modes[k]["matches_golden"] = False
    write(p, json.dumps(d, ensure_ascii=False, indent=2))
    rp = report(root)
    write(rp, read(rp) + "\n补充披露：模式 %s 与黄金产物不一致（match=False）。\n" % k)


#: (id, 说明, A 面变异函数, 期望红项集)。期望集为空＝正向面。
A_MUTATIONS = [
    ("M1", "模式记录缺 sha256（旧版 `continue` 静默放行）⇒ 恰好 R8", m_drop_sha256, {"R8"}),
    ("M2", "matches_golden=false 且报告未同一行披露 ⇒ 恰好 R8", m_mismatch_silent, {"R8"}),
    ("M3", "matches_golden 是字符串 \"false\"（非布尔）⇒ 恰好 R8", m_nonbool_flag, {"R8"}),
    ("M4", "summary 整个少了 modes 键 ⇒ 恰好 R8", m_drop_modes, {"R8"}),
    ("M5", "模式记录不是对象（值为字符串）⇒ 恰好 R8", m_record_not_object, {"R8"}),
    ("M6", "summary 是坏 JSON ⇒ 恰好 R8", m_broken_summary, {"R8"}),
    ("M7", "正向：缺 sha256 但报告同一行声明「未产出指纹」⇒ 0 红", m_missing_declared, set()),
    ("M8", "正向：不一致且报告同一行披露 ⇒ 0 红", m_mismatch_disclosed, set()),
]


def _run():
    d0 = scratch_copy(ROOT)
    tmp = tempfile.mkdtemp(prefix="crev-fc-tmp-")
    try:
        # ---------------------------------------------------------- A 面：守卫
        if not MUTATE_ONLY:
            red, rc = run_guard(d0)
            check("A-F1 正向：真实交付集 0 红", red == [] and rc == 0, "红项=%s rc=%s" % (red, rc))
            modes = (json.loads(read(summary_path(d0))) or {}).get("modes") or {}
            ok = bool(modes) and all(isinstance(r, dict)
                                     and isinstance(r.get("sha256"), str) and len(r["sha256"]) == 64
                                     and isinstance(r.get("matches_golden"), bool)
                                     for r in modes.values())
            check("A-U1 真实 summary 的每个模式都带 64 位 sha256 与布尔 matches_golden", ok,
                  "模式=%s" % sorted(modes))

        for mid, desc, fn, expect in A_MUTATIONS:
            sb = scratch_copy(ROOT)
            try:
                fn(sb)
            except AnchorMiss as e:
                print("ANCHOR-MISS %s" % e)
                return 2
            try:
                red, rc = run_guard(sb)
            finally:
                shutil.rmtree(sb, ignore_errors=True)
            check("A-%s 变异：%s" % (mid, desc), set(red) == set(expect),
                  "期望=%s 实得=%s rc=%s" % (sorted(expect), red, rc))

        # ---------------------------------------------------------- B 面：runner 真跑
        if MUTATE_ONLY:
            return _finish()
        impl = os.path.join(tmp, "fake_impl.py")
        write(impl, FAKE_IMPL)
        write(os.path.join(tmp, "fakew_impl.py"), FAKE_IMPL_WRITES)
        src = os.path.join(ROOT, "bench", "cross_eval", "harness", "runner.py")

        rc, out, rawdir = run_runner(d0, tmp, "ok,boom,ng")
        check("B1 有失败模式时 runner 必须非零退出（旧版 EXIT=0）", rc != 0,
              "rc=%s 末行=%r" % (rc, out.strip().splitlines()[-1:] ))
        check("B2 失败模式以 `FAILED modes=…` 点名", "FAILED modes=" in out and "boom" in out,
              "输出片段=%r" % [l for l in out.splitlines() if l.startswith("FAILED")][:1])

        sm = {}
        sp = os.path.join(rawdir, "fake_summary.json")
        if os.path.isfile(sp):
            sm = json.loads(read(sp))
        modes = sm.get("modes") or {}
        check("B3 结论字段：异常模式 conclusion=FAIL、自报 ok=False 亦 FAIL、正常模式 OK",
              modes.get("boom", {}).get("conclusion") == "FAIL"
              and modes.get("ng", {}).get("conclusion") == "FAIL"
              and modes.get("ok", {}).get("conclusion") == "OK",
              "conclusions=%s" % {k: v.get("conclusion") for k, v in modes.items()})
        ev = modes.get("ok", {})
        check("B4 证据键全量搬运：引擎自报的非白名单键进入 summary 并记名 carried_keys",
              ev.get("custom_evidence_key") == {"nested": [1, 2]} and "trace" in ev
              and isinstance(ev.get("carried_keys"), list)
              and "custom_evidence_key" in ev["carried_keys"],
              "carried=%s" % ev.get("carried_keys"))
        check("B5 不可序列化键**记名**在 dropped_keys，不静默消失",
              "unserializable" in (ev.get("dropped_keys") or []),
              "dropped=%s" % ev.get("dropped_keys"))
        txt = read(os.path.join(rawdir, "fake_ok.txt")) if os.path.isfile(
            os.path.join(rawdir, "fake_ok.txt")) else ""
        check("B6 原始文本落 `REC` 证据行与 `EVIDENCE carried=… dropped=…` 行",
              "\nREC {" in "\n" + txt and "EVIDENCE carried=" in txt,
              "txt 头=%r" % txt.splitlines()[:2])
        check("B7 cfg[\"mode\"] 送达实现（旧版 cfg_for 的 mode 形参零引用）",
              ev.get("cfg_mode") == "ok" and modes.get("ng", {}).get("cfg_mode") == "ng",
              "cfg_mode=%s/%s" % (ev.get("cfg_mode"), modes.get("ng", {}).get("cfg_mode")))

        rc2, out2, _rd2 = run_runner(d0, tmp, "ok")
        check("B8 全模式正常 ⇒ 退出码 0 且打印 ALL_MODES_OK n",
              rc2 == 0 and "ALL_MODES_OK 1" in out2,
              "rc=%s 末行=%r" % (rc2, out2.strip().splitlines()[-1:]))

        rc3, out3, rawdir3 = run_runner(d0, tmp, "ok", impl="fakew_impl.py", name="fakew")
        sp3 = os.path.join(rawdir3, "fakew_summary.json")
        rec3 = (json.loads(read(sp3)).get("modes") or {}).get("ok", {}) if os.path.isfile(sp3) else {}
        check("B9 有产物时落 sha256/matches_golden，且 matches_golden 为布尔（R8 的输入面）",
              rc3 == 0 and isinstance(rec3.get("sha256"), str) and len(rec3.get("sha256") or "") == 64
              and rec3.get("matches_golden") is False,
              "rec=%s" % {k: rec3.get(k) for k in ("sha256", "matches_golden", "conclusion")})

        gsrc = read(os.path.join(d0, "scripts", "check_reviews.py"))
        anchors = ("R8_MISSING_MARK", "R8_MISMATCH_MARK", "SHA256_HEX_RE", "not modes")
        check("A-U2 静态：R8 的三个标记常量与「modes 为空也判红」在库",
              all(a in gsrc for a in anchors), "缺=%s" % [a for a in anchors if a not in gsrc])
        rsrc = read(src)
        ranchors = ("sys.exit(main())", "FAILED modes=", "carried_keys", "dropped_keys",
                    "conclusion_of", '"mode": mode')
        check("B10 静态：runner 的失败退出/结论字段/证据搬运/cfg mode 锚点在库（防回退）",
              all(a in rsrc for a in ranchors),
              "缺=%s" % [a for a in ranchors if a not in rsrc])
        return _finish()
    finally:
        shutil.rmtree(d0, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def _finish():
    if QUIET:
        for n in _fails:
            print("RED %s" % n)
        print("RAN %d" % (_pass + _fail))
    print("通过 %d / 失败 %d" % (_pass, _fail))
    return 1 if _fail else 0


# 模块级即跑（standalone 守卫件体例：直接被 `python tests/xxx.py` 执行，不经 pytest 收集）。
sys.exit(_run())
