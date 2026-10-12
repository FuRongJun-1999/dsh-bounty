# -*- coding: utf-8 -*-
"""test_review_build —— 插件测评站生成器守卫（断言 ＋ 定点变异自证）。

对象：`scripts/review_build.py`（静态站生成器——**纯函数 + 写盘**，零网络、纯 stdlib）。
真源：`review/data/plugins.json`（测评记录）＋ `review/data/method.json`（方法说明）。

为什么另立本件：测评站的成立前提是**两条映射规则**，不是渲染细节——
① 「每条测评记录都必须带 命令 ＋ 已采集的原始输出 ＋ 出处」（缺一条就不许建站）；
② 「模型工具面成本读不到时，是数据缺口，不是 0 成本」（不许拿 0 冒充）。
故本件 = ①逐条正反断言（真源 → 页面／榜面的每条映射）＋ ②每条映射一个**定点变异**
（把该映射短路 ⇒ 对应断言**必然转红**且**恰好**转红，多红=断言语义纠缠、少红=判据空转）。

断言组：
  [J] 映射面：转义 / 条目校验 / 证据必填 / 尺寸下限 / 必测对象 / 排序 / import 白名单 / 内存面渲染
  [K] 落盘面：退出码 / ≥4 页齐 / 每插件一页 / 转义 / 逐字节确定 / 坏输入 fail-closed（真跑子进程）

★ 为什么 [J] 组里另设 J15–J18：`[K]` 组是 `subprocess` 真跑，**变异只改内存副本**（不落盘，
故子进程读到的仍是原文件）——凡「渲染/下限」类映射必须在内存面留一条断言，
否则变异无从影响子进程，`--mutate` 会假绿。

用法：
  python -X utf8 tests/test_review_build.py            # 正向：全断言
  python -X utf8 tests/test_review_build.py --mutate   # 定点变异自证（逐条必红）
  python -X utf8 tests/test_review_build.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中期望红项；1 = 有断言失败 / 变异未按预期转红；
        2 = ANCHOR-MISS（变异锚点在实现里命中次数 ≠1——实现漂移即硬失败）。
"""
from __future__ import annotations

import copy
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))          # <仓根>/tests
REPO = os.path.dirname(HERE)                               # <仓根>
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import review_build as rb                                            # noqa: E402

IMPL = os.path.join(SCRIPTS, "review_build.py")
DATA = os.path.join(REPO, "review", "data")

PASS = 0
FAIL = 0
FAILS = []

#: 注入夹具：出现在**会被页面渲染**的字段（插件名）上——用来证转义是活的。
INJECT_NAME = 'eve<img src=x onerror=alert(1)>'


def ok(name, cond, detail=""):
    """逐条记账：`[PASS]` / `[FAIL] name · detail`（同仓 tests/test_*.py 体例）。"""
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


# 生效条件：无必需形参时返回仓内真源（review/data/plugins.json ＋ method.json）的解析结果。
def real_doc():
    with io.open(os.path.join(DATA, "plugins.json"), encoding="utf-8") as fh:
        return json.load(fh)


# 生效条件：无必需形参时返回一份**仓内真源**的深拷贝副本（可直接改字段当坏输入夹具）。
def fixture_doc():
    doc = copy.deepcopy(real_doc())
    for rec in doc["plugins"]:
        rec["source_url"] = "https://example.invalid/" + rec["id"]
    return doc


# 生效条件：无必需形参时返回仓内真源经 load_plugins 校验后的条目列表（供内存面渲染断言用）。
def real_plugins():
    return rb.load_plugins(real_doc())


# 生效条件：apply 为对「真源条目列表副本」的改动函数时返回页面清单（抛 DataError 则返回空列表，让断言可判而变异体不炸）——供「下限闸」类断言用。
def pages_after(apply=lambda pl: pl):
    recs = copy.deepcopy(real_plugins())
    apply(recs)
    try:
        return rb.site_data(recs, method_doc())
    except rb.DataError:
        return []


# 生效条件：无必需形参时返回仓内 method.json 的解析结果。
def method_doc():
    with io.open(os.path.join(DATA, "method.json"), encoding="utf-8") as fh:
        return json.load(fh)


# 生效条件：mutate 为单条记录的改动函数时返回 DataError 的**消息文本**（不抛则返回空串）——用于逐条验校验闸，并区分是「哪一道闸」拦下的。
def rejects(mutate):
    doc = fixture_doc()
    mutate(doc)
    try:
        rb.load_plugins(doc)
        return ""
    except rb.DataError as exc:
        return str(exc)


# ================================================================ [J] 映射面


def group_mapping():
    print("[J] 映射面（转义 / 条目校验 / 证据必填 / 下限 / 必测对象 / 排序 / import 白名单 / 内存面渲染）")

    ok("J1 HTML 转义：不可信文本里的标签与引号都被转义",
       rb.esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
       and rb.esc('" onload="x') == "&quot; onload=&quot;x",
       rb.esc('" onload="x'))

    doc = fixture_doc()
    recs = rb.load_plugins(doc)
    ok(f"J2 真源三插件全部载入且不崩（{len(recs)} 条）",
       len(recs) == 3 and [r["id"] for r in recs] == list(rb.REQUIRED_PLUGIN_IDS),
       [r["id"] for r in recs])

    ok("J3 每条测评记录齐备必备字段（名称/版本/来源 URL/维度/证据/结论/边界）",
       all(all(k in r for k in rb.REQUIRED_PLUGIN_FIELDS) for r in recs)
       and all(r["source_url"].startswith("http") for r in recs),
       [sorted(set(rb.REQUIRED_PLUGIN_FIELDS) - set(r)) for r in recs])

    ok("J4 每条记录 ≥1 条证据，且每条证据都带命令与原始输出",
       all(len(r["evidence"]) >= 1 for r in recs)
       and all(str(e.get("command") or "").strip() and str(e.get("output") or "").strip()
               for r in recs for e in r["evidence"]),
       [(r["id"], len(r["evidence"])) for r in recs])

    ok("J5 证据必填校验是活的：把任一记录的证据清空 ⇒ 响亮失败",
       "证据" in rejects(lambda d: d["plugins"][0].update({"evidence": []})),
       rejects(lambda d: d["plugins"][0].update({"evidence": []})))

    bad_field = rejects(lambda d: d["plugins"][0].pop("version_source"))
    bad_json = False
    try:
        rb.load_data(os.path.join(tempfile.gettempdir(), "__review_build_no_such_dir__"))
    except rb.DataError:
        bad_json = True
    ok("J6 坏输入 fail-closed：缺字段 / 目录不存在 ⇒ DataError（不静默跳过）",
       bool(bad_field) and bad_json, (bad_field, bad_json))

    ok("J7 固定测评对象缺席 ⇒ fail-closed（条数够，但三支里少一支就拒）",
       "缺席" in rejects(lambda d: [r.update({"id": "dsh-something-else",
                                              "name": "dsh-something-else"})
                                    for r in d["plugins"] if r["id"] == "dsh-cost-meter"]),
       rejects(lambda d: [r.update({"id": "dsh-something-else", "name": "dsh-something-else"})
                          for r in d["plugins"] if r["id"] == "dsh-cost-meter"]))

    ok("J8 尺寸下限被强制执行：条目 <3 条被拒（点名下限），且页数下限常量 ≥4",
       "测评条目" in rejects(lambda d: d.update({"plugins": d["plugins"][:2]}))
       and rb.MIN_PAGES >= 4 and rb.MIN_PLUGINS >= 3,
       (rb.MIN_PAGES, rb.MIN_PLUGINS, rejects(lambda d: d.update({"plugins": d["plugins"][:2]}))))

    ordered = rb.rank_plugins(recs)
    toks = [(r["id"], r.get("tool_tokens")) for r in ordered]
    ok("J9 榜单排序可复算：有工具面读数的排在读不到的前面，且同档按证据条数/id 定序",
       [t[0] for t in toks][0] == "dsh-better-sidebar"
       and toks[0][1] == 324
       and [t[0] for t in toks] == [r["id"] for r in
                                    sorted(recs, key=lambda r: rb._sort_key(r))],
       toks)

    bad = rb.import_allowlist()
    names = rb.import_names()
    ok("J10 纯 stdlib、不触网：import 白名单自检为空，且禁止模块（socket/urllib/http/subprocess）零出现",
       bad == [] and not (set(names) & set(rb.FORBIDDEN_IMPORTS)) and "json" in names,
       (bad, sorted(names)))

    ok("J11 测评维度校验是活的：维度清空 / 维度缺 name ⇒ 响亮失败",
       "dimensions" in rejects(lambda d: d["plugins"][0].update({"dimensions": []}))
       and "维度" in rejects(lambda d: d["plugins"][0]["dimensions"][0].pop("name")),
       rejects(lambda d: d["plugins"][0].update({"dimensions": []})))

    ok("J12 来源 URL 校验是活的：非 http(s) 的 source_url ⇒ 响亮失败",
       "source_url" in rejects(lambda d: d["plugins"][0].update({"source_url": "见文档"})),
       rejects(lambda d: d["plugins"][0].update({"source_url": "见文档"})))

    ok("J13 边界必填：boundaries 空 ⇒ 响亮失败（验收要求每条含边界）",
       "boundaries" in rejects(lambda d: d["plugins"][0].update({"boundaries": []})),
       rejects(lambda d: d["plugins"][0].update({"boundaries": []})))

    ok("J14 证据字段校验是活的：证据缺 command 或缺 output ⇒ 响亮失败",
       "command" in rejects(lambda d: d["plugins"][0]["evidence"][0].pop("command"))
       and "output" in rejects(lambda d: d["plugins"][0]["evidence"][0].pop("output")),
       (rejects(lambda d: d["plugins"][0]["evidence"][0].pop("command")),
        rejects(lambda d: d["plugins"][0]["evidence"][0].pop("output"))))

    mdoc = fixture_doc()
    mdoc["plugins"][0]["name"] = INJECT_NAME
    mrecs = rb.load_plugins(mdoc)
    meth = method_doc()
    idx = rb.render_index(mrecs, meth)
    ok("J15 页面渲染走转义出口：[J] 组内直接调渲染函数，注入文本不出现、转义形态出现",
       INJECT_NAME not in idx and "&lt;img" in idx,
       idx[idx.find("eve"):idx.find("eve") + 60])

    pl = pages_after()
    ok(f"J16 页数下限在内存面同样成立（≥{rb.MIN_PAGES} 页且首页/榜单/方法齐）",
       len(pl) >= rb.MIN_PAGES
       and {"index.html", "ranking.html", "method.html"}.issubset({n for n, _ in pl}),
       [n for n, _ in pl])

    ok("J17 页面不含生成时刻（确定性判据 _now_stamp 返回空串，渲染里无「生成于」）",
       rb._now_stamp() == "" and "生成于" not in idx, rb._now_stamp())

    ok("J18 条目下限同样在内存面拦下（只给 2 条 ⇒ 抛错、不返回页）",
       pages_after(lambda pl: pl.pop()) == [], [r["id"] for r in real_plugins()])


# ================================================================ [K] 落盘面

# 生效条件：argv 为命令行参数列表时以子进程真跑生成器（cwd=仓根、UTF-8、超时 300s），返回 CompletedProcess。
def run_impl(*argv):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-X", "utf8", IMPL, *argv],
                          cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=300)


# 生效条件：无必需形参时把「注入名 + 空证据」的坏夹具写进临时 data 目录，返回 (目录, 插件文件名集合)。
def write_bad_fixture(tmp):
    doc = fixture_doc()
    doc["plugins"][0]["name"] = INJECT_NAME
    ddir = os.path.join(tmp, "data")
    os.makedirs(ddir, exist_ok=True)
    with io.open(os.path.join(ddir, "plugins.json"), "w", encoding="utf-8",
                 newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    with io.open(os.path.join(DATA, "method.json"), encoding="utf-8") as fh:
        with io.open(os.path.join(ddir, "method.json"), "w", encoding="utf-8",
                     newline="\n") as out:
            out.write(fh.read())
    names = sorted(["index.html", "ranking.html", "method.html"]
                   + [rb.detail_file(r["id"]) for r in doc["plugins"]])
    return ddir, names


def group_build(tmp):
    print("[K] 落盘面（退出码 / ≥4 页齐 / 每插件一页 / 转义 / 逐字节确定 / 坏输入——真跑子进程）")
    ddir, names = write_bad_fixture(tmp)
    out1 = os.path.join(tmp, "s1")
    out2 = os.path.join(tmp, "s2")
    r1 = run_impl("--data", ddir, "--out", out1)
    r2 = run_impl("--data", ddir, "--out", out2)
    ok("K1 生成器退出码 0（真源 → 落盘）", r1.returncode == 0,
       (r1.returncode, (r1.stderr or "")[-200:]))
    got = sorted(os.listdir(out1)) if os.path.isdir(out1) else []
    ok(f"K2 产出页齐且 ≥{rb.MIN_PAGES} 页（首页/榜单/方法 ＋ 每插件一页）",
       got == names and len(got) >= rb.MIN_PAGES, (got, names))

    detail = os.path.join(out1, rb.detail_file("dsh-better-sidebar"))
    txt = io.open(detail, encoding="utf-8").read() if os.path.exists(detail) else ""
    ok("K3 每个插件各有详情页，且页内含其版本号与证据段落",
       all(os.path.exists(os.path.join(out1, rb.detail_file(r["id"])))
           for r in fixture_doc()["plugins"])
       and "0.25.0" in txt and "可复跑证据" in txt and "<pre>" in txt,
       detail)

    alltext = "\n".join(io.open(os.path.join(out1, n), encoding="utf-8").read()
                        for n in got) if got else ""
    ok("K4 真源里的注入文本进页面后被转义（原文不出现、转义形态出现）",
       INJECT_NAME not in alltext
       and "&lt;img src=x onerror=alert(1)&gt;" in alltext,
       alltext[alltext.find("eve"):alltext.find("eve") + 60])

    same = bool(got) and all(
        io.open(os.path.join(out1, n), encoding="utf-8").read()
        == io.open(os.path.join(out2, n), encoding="utf-8").read() for n in got)
    ok("K5 确定性：两次生成逐字节相同，且不含生成时刻（页面里没有 `生成于` 之类的时间戳）",
       same and "生成于" not in alltext and rb._now_stamp() == "",
       (same, rb._now_stamp()))

    empty = fixture_doc()
    empty["plugins"][1]["evidence"] = []
    bad_dir = os.path.join(tmp, "bad")
    os.makedirs(bad_dir, exist_ok=True)
    with io.open(os.path.join(bad_dir, "plugins.json"), "w", encoding="utf-8") as fh:
        json.dump(empty, fh, ensure_ascii=False)
    shutil.copyfile(os.path.join(DATA, "method.json"),
                    os.path.join(bad_dir, "method.json"))
    r3 = run_impl("--data", bad_dir, "--out", os.path.join(tmp, "s3"))
    ok("K6 记录缺证据 ⇒ fail-closed 退出码 2（不把缺证据的记录建站）",
       r3.returncode == 2 and "证据" in (r3.stderr or ""),
       (r3.returncode, (r3.stderr or "")[-160:]))

    broken = os.path.join(tmp, "broken")
    os.makedirs(broken, exist_ok=True)
    with io.open(os.path.join(broken, "plugins.json"), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    with io.open(os.path.join(broken, "method.json"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    r4 = run_impl("--data", broken, "--out", os.path.join(tmp, "s4"))
    ok("K7 坏 JSON ⇒ fail-closed 退出码 2（不静默当成功）",
       r4.returncode == 2, (r4.returncode, (r4.stderr or "")[-160:]))

    r5 = run_impl("--data", ddir, "--out", os.path.join(tmp, "s5"), "--print")
    ok("K8 --print 只打印不落盘（退出码 0，stdout 含页头）",
       r5.returncode == 0 and "===== index.html =====" in (r5.stdout or "")
       and not os.path.isdir(os.path.join(tmp, "s5")),
       (r5.returncode, (r5.stdout or "")[:80]))

    out6 = os.path.join(tmp, "s6")
    r6 = run_impl("--data", DATA, "--out", out6)
    ok("K9 仓内真源直接可生成：退出码 0 且页内出现三支测评对象与它们现取的版本号",
       r6.returncode == 0
       and all(pid in "\n".join(io.open(os.path.join(out6, n), encoding="utf-8").read()
                                for n in sorted(os.listdir(out6)))
               for pid in rb.REQUIRED_PLUGIN_IDS)
       and "0.25.0" in io.open(os.path.join(out6, "index.html"), encoding="utf-8").read(),
       (r6.returncode, sorted(os.listdir(out6)) if os.path.isdir(out6) else None))

    ok("K10 每页都是自包含 UTF-8（charset meta ＋ 不引任何会被加载的外部资源：src=http / @import / url(http）",
       all('<meta charset="utf-8">' in io.open(os.path.join(out1, n), encoding="utf-8").read()
           and not any(marker in io.open(os.path.join(out1, n), encoding="utf-8").read()
                       for marker in ('src="http', "src='http", 'url(http', "@import"))
           for n in got) if got else False, got)


_GROUPS = (group_mapping,)


# 生效条件：无必需形参时清账并跑 [J] 全组（落盘子进程组由调用方另跑），返回失败项前缀集合。
def run_suite():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    for fn in _GROUPS:
        fn()
    return {n.split(" ", 1)[0] for n in FAILS}


# ================================================================ 定点变异（注入映射失效 ⇒ 必红）
# 每条变异 = 把**一条映射**短路（源码级、只改内存里 exec 的副本，不落盘），
# 期望转红的断言项**恰好**等于声明集合：多红 = 断言语义纠缠，少红 = 该映射空转。

_MUTATIONS = (
    ("N0 关证据必填闸（空证据也放行）",
     "    if not isinstance(evs, list) or len(evs) < MIN_EVIDENCE:",
     "    if False:  # MUT", {"J5"}),
    ("N1 关条目下限闸（2 条也建站）",
     "    if len(plugins) < MIN_PLUGINS:\n"
     "        raise DataError(f\"测评条目 {len(plugins)} 条 < {MIN_PLUGINS}（验收要求 ≥3 个插件）\")\n",
     "    # MUT: 下限闸被关\n", {"J8"}),
    ("N2 关渲染转义（真源文本直出页面）",
     "    return html.escape(str(text), quote=True)",
     "    return str(text)  # MUT", {"J1", "J15"}),
    ("N3 关排序（按入参原序出榜）",
     "    return sorted(plugins, key=_sort_key)",
     "    return sorted(plugins, key=lambda r: 0)  # MUT", {"J9"}),
    ("N4 关页数下限闸（三页也当合格整站返回）",
     "    pages.append((\"method.html\", render_method(method)))\n"
     "    if len(pages) < MIN_PAGES:\n"
     "        raise DataError(f\"产出 {len(pages)} 页 < {MIN_PAGES}（验收要求 ≥4 页）\")\n",
     "    pages = pages[:3]  # MUT：既丢 method 页，又拆掉页数闸\n", {"J16"}),
    ("N5 注入生成时刻（破坏确定性）",
     '    """确定性判据：不注入任何时刻信息。"""\n    return ""',
     '    """MUT：注入时刻。"""\n    return "<div>生成于 2026-10-13 00:00:00</div>"',
     {"J17"}),
    ("N6 关条目下限闸（2 条也当合格整站返回）",
     "    if len(plugins) < MIN_PLUGINS:\n"
     "        raise DataError(f\"详情页 {len(plugins)} 个 < {MIN_PLUGINS}（验收要求 ≥3 个插件）\")\n",
     "    pass  # MUT：条目下限闸被关\n", {"J18"}),
)


#: 变异 → 目标函数（锚点落在哪个函数里就变异哪个）。
_MUT_TARGETS = (("N0", "evidence_of"), ("N1", "plugin_list"), ("N2", "esc"),
                ("N3", "rank_plugins"), ("N4", "site_data"), ("N5", "_now_stamp"),
                ("N6", "site_data"))


class AnchorMiss(Exception):
    pass


# 生效条件：fn_name 为模块内函数名、old 为唯一锚点、new 为替换文本时，用 inspect.getsource 取该函数源码，就地 exec 到模块全局（运行中的实现被替换），返回复原函数；锚点命中次数 ≠1 抛 AnchorMiss。
def _mut_source(fn_name, old, new):
    orig = getattr(rb, fn_name)
    src = inspect.getsource(orig)
    if src.count(old) != 1:
        raise AnchorMiss(f"{fn_name}: 锚点命中 {src.count(old)} 次（期望 1）：{old!r}")
    exec(compile(src.replace(old, new), f"<review-{fn_name}-mut>", "exec"),
         vars(rb))

    def _restore():
        setattr(rb, fn_name, orig)
    return _restore


def _anchor_preflight():
    """锚点自检：任一锚点在当前实现里命中次数 ≠1 → ANCHOR-MISS（退出码 2）。"""
    bad = []
    for (name, _old, _new, _exp), (_mid, fn) in zip(_MUTATIONS, _MUT_TARGETS):
        src = inspect.getsource(getattr(rb, fn))
        if src.count(_old) != 1:
            bad.append((name, src.count(_old)))
    if not bad:
        return 0
    for name, n in bad:
        print(f"  ANCHOR-MISS {name}：锚点命中 {n} 次（期望 1）")
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _mutate_mode():
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：逐条短路一条映射，对应断言必须**恰好**转红\n")
    base_red = run_suite()
    print(f"\n  未变异基线：红项 {len(base_red)} "
          f"{'（应为 0）' if not base_red else sorted(base_red)}")
    bad = []
    if base_red:
        bad.append(f"基线即转红：{sorted(base_red)}")
    for (name, old, new, expect), (_mid, fn) in zip(_MUTATIONS, _MUT_TARGETS):
        restore = _mut_source(fn, old, new)
        try:
            red = run_suite()
        except Exception as exc:                                  # noqa: BLE001
            red = {f"<变异体异常:{type(exc).__name__}>"}
        finally:
            restore()
        hit = red == set(expect)
        if not hit:
            bad.append(f"{name}：红项 {sorted(red)} ≠ 期望 {sorted(expect)}")
        print(f"  {'[PASS]' if hit else '[FAIL]'} {name}：红项 {len(red)}"
              f"（期望 {len(expect)}）"
              + ("" if hit else f" 实={sorted(red)} 期={sorted(expect)}"))
    print("\n定点变异：" + ("PASS（逐条恰好命中期望红项）" if not bad
                            else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--list" in argv:
        for name, _old, _new, exp in _MUTATIONS:
            print(f"  {name:<40} expect_red={len(exp)} {sorted(exp)}")
        return 0
    if "--mutate" in argv:
        return _mutate_mode()

    print("插件测评站生成器守卫（scripts/review_build.py · 真源→页面映射断言）")
    print("=" * 74)
    for fn in _GROUPS:
        fn()
    tmp = tempfile.mkdtemp(prefix="review_site_guard_")
    try:
        group_build(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("=" * 74)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
        return 1
    print("ALL OK（反面证明见 --mutate）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
