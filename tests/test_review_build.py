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

★ 两组各自怎么被变异覆盖（**两条路径都在 --mutate 里真跑**）：
  · [J] 变异 = 内存副本（`inspect.getsource` + `exec`）⇒ 影响同进程内的 J 断言；
  · [K] 变异 = 把变异源码写进**临时目录**，临时把 `IMPL` 指向该副本 ⇒ **子进程真读变异体**，
    于是 K 断言能真转红。（早期版本只变异内存副本，对「真跑子进程」的 K 组零覆盖——
    复核者反证：拆掉生成器的 fail-closed 校验后 `--mutate` 仍报 PASS，而默认模式 K7 转红。）
    `--mutate` 会**显式打印 K 组的覆盖映射与未被专项变异的 K 断言**，不许让它看起来是全覆盖。

用法：
  python -X utf8 tests/test_review_build.py            # 正向：全断言
  python -X utf8 tests/test_review_build.py --mutate   # 定点变异自证（逐条必红，两组都跑）
  python -X utf8 tests/test_review_build.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中期望红项；1 = 有断言失败 / 变异未按预期转红；
        2 = ANCHOR-MISS（变异锚点在实现里命中次数 ≠1——实现漂移即硬失败）。
"""
from __future__ import annotations

import contextlib
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
    # S1 修：只断言「三支都在」，不把真源 JSON 的数组顺序当判据（顺序由 J9 的排序断言管）。
    ok(f"J2 真源三插件全部载入且不崩（{len(recs)} 条；只判集合，不判数组顺序）",
       len(recs) == 3 and {r["id"] for r in recs} == set(rb.REQUIRED_PLUGIN_IDS),
       [r["id"] for r in recs])

    # I2 修：原版只重述 load_plugins 已保证的不变量（恒真、无变异覆盖）。
    # 现在补上「缺任一必备字段都被闸点名」的反向子句 ⇒ 关掉必备字段闸时本条必转红。
    # （id 缺失由 plugin_list 的更早一道闸点名「有条目缺 id」，其余字段由 _check_record 的
    #  必备字段闸点名「缺字段 X」——两条都算「被点名拦下」。）
    missing_msgs = {f: rejects(lambda d, f=f: d["plugins"][0].pop(f))
                    for f in rb.REQUIRED_PLUGIN_FIELDS}
    ok("J3 每条测评记录齐备必备字段，且缺任一必备字段都被校验闸点名拦下",
       all(all(k in r for k in rb.REQUIRED_PLUGIN_FIELDS) for r in recs)
       and all(msg and ("缺字段" in msg or "缺 id" in msg)
               for msg in missing_msgs.values()),
       missing_msgs)

    # S2 修：原版从不调用 rb.evidence_of，真守卫是 J5（N0 短路后 J4 恒绿）。现在真调用它。
    ok("J4 每条记录 ≥1 条证据，且每条证据都带命令与原始输出（经 evidence_of 真调用校验）",
       all(len(rb.evidence_of(r)) >= 1 for r in recs)
       and all(str(e.get("command") or "").strip() and str(e.get("output") or "").strip()
               for r in recs for e in rb.evidence_of(r)),
       [(r["id"], len(rb.evidence_of(r))) for r in recs])

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

    # I2 修：原版两处各自调 rejects（详情与判据是两次独立调用），且只吃「缺席」一条。
    # 现在把 `rejects(...)` 结果先落到局部变量（判据与详情同源），并补一条独立的 id 重复子句。
    miss = rejects(lambda d: [r.update({"id": "dsh-something-else",
                                        "name": "dsh-something-else"})
                              for r in d["plugins"] if r["id"] == "dsh-cost-meter"])
    dup = rejects(lambda d: d["plugins"][1].update({"id": d["plugins"][0]["id"]}))
    ok("J7 固定测评对象缺席 ⇒ fail-closed；且 id 重复同样被点名拒（条数够也不放行）",
       "缺席" in miss and "重复" in dup, (miss, dup))

    # S4 修：原版另加了 `rb.MIN_PAGES >= 4` 的常量自洽子句（不是对实现的独立检查）。
    # 常量自洽不构成证据，删掉；页数下界的真检查是 J16（内存面）与 K2（落盘面）。
    ok("J8 尺寸下限被强制执行：条目 <3 条被拒且点名下限",
       "测评条目" in rejects(lambda d: d.update({"plugins": d["plugins"][:2]})),
       rejects(lambda d: d.update({"plugins": d["plugins"][:2]})))

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

    # S3 修：原版只测 render_index。现在四个渲染出口全测（它们都经 page() → _now_stamp()）。
    no_stamp = [rb.render_index(mrecs, meth), rb.render_ranking(mrecs, meth),
                rb.render_method(meth), rb.render_plugin(mrecs[0], meth)]
    ok("J17 四个渲染出口都不含生成时刻（确定性判据 _now_stamp 返回空串，渲染里无「生成于」）",
       rb._now_stamp() == "" and all("生成于" not in p for p in no_stamp),
       rb._now_stamp())

    ok("J18 条目下限同样在内存面拦下（只给 2 条 ⇒ 抛错、不返回页）",
       pages_after(lambda pl: pl.pop()) == [], [r["id"] for r in real_plugins()])


# ================================================================ [K] 落盘面

# 生效条件：argv 为命令行参数列表时以子进程真跑生成器（cwd=仓根、UTF-8、超时 300s），返回 CompletedProcess。
# 注意：目标文件取模块级 IMPL —— [K] 面变异会把它临时指向临时目录里的变异副本。
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
       os.path.relpath(detail, tmp))

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
    pages6 = ({n: io.open(os.path.join(out6, n), encoding="utf-8").read()
               for n in sorted(os.listdir(out6))} if os.path.isdir(out6) else {})
    idx6 = pages6.get("index.html", "")
    # S3 修：原版硬编码 "0.25.0"。改成从真源读版本号——数据变了断言跟着走，不再钉死一个常量。
    real_vers = [str(r["version"]) for r in real_doc()["plugins"]]
    ok("K9 仓内真源直接可生成：退出码 0，页内出现三支测评对象与它们各自的（数据驱动的）版本号",
       r6.returncode == 0
       and all(pid in "\n".join(pages6.values()) for pid in rb.REQUIRED_PLUGIN_IDS)
       and all(v in idx6 for v in real_vers),
       (r6.returncode, real_vers, sorted(pages6)))

    # S3 修：原版只扫 out1。现在把「实跑仓内真源」的产物目录 out6 也纳入扫描。
    scan = []
    for d in (out1, out6):
        for n in (sorted(os.listdir(d)) if os.path.isdir(d) else []):
            scan.append(io.open(os.path.join(d, n), encoding="utf-8").read())
    ok("K10 每页都是自包含 UTF-8（charset meta ＋ 不引任何会被加载的外部资源：src=http / @import / url(http）——两轮产物目录都扫",
       bool(scan) and all('<meta charset="utf-8">' in t
                          and not any(marker in t for marker in
                                      ('src="http', "src='http", 'url(http', "@import"))
                          for t in scan),
       len(scan))


_GROUPS = (group_mapping,)


# 生效条件：report_all 为假（默认）时清账并跑 [J] 全组，返回失败项前缀集合；quiet 为真时只打印失败行（变异模式用，避免每条变异都重印全组）。
def run_suite(quiet=False):
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    if quiet:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            for fn in _GROUPS:
                fn()
        for line in buf.getvalue().splitlines():
            if "[FAIL]" in line:
                print("      " + line.strip())
    else:
        for fn in _GROUPS:
            fn()
    return {n.split(" ", 1)[0] for n in FAILS}


# 生效条件：tmp 为临时工作目录时清账并跑 [K] 全组（真跑子进程），返回失败项前缀集合；quiet 为真时只在失败时打印。
def run_suite_k(tmp, quiet=True):
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    if quiet:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            group_build(tmp)
        for line in buf.getvalue().splitlines():
            if "[FAIL]" in line:
                print("      " + line.strip())
    else:
        group_build(tmp)
    return {n.split(" ", 1)[0] for n in FAILS}


# ================================================================ 定点变异（注入映射失效 ⇒ 必红）
# [J] 面：每条变异 = 把**一条映射**短路（源码级、只改内存里 exec 的副本，不落盘），
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
    # I2 新增：给 J3 接上变异覆盖（关掉必备字段闸 ⇒ J3 的反向子句必红）。
    ("N7 关必备字段闸（缺字段不再点名）",
     "    for field in REQUIRED_PLUGIN_FIELDS:\n"
     "        if field not in rec:\n"
     "            raise DataError(f\"{pid}：缺字段 {field}\")\n",
     "    # MUT：必备字段闸被关\n", {"J3"}),
    # I2 新增：给 J7 接上变异覆盖（关掉固定对象缺席闸 ⇒ J7 必红）。
    ("N8 关固定测评对象缺席闸",
     "    if missing:\n"
     "        raise DataError(\"固定测评对象缺席：\" + \"，\".join(missing))\n",
     "    # MUT：缺席闸被关\n", {"J7"}),
)


#: 变异 → 目标函数（锚点落在哪个函数里就变异哪个）。
_MUT_TARGETS = (("N0", "evidence_of"), ("N1", "plugin_list"), ("N2", "esc"),
                ("N3", "rank_plugins"), ("N4", "site_data"), ("N5", "_now_stamp"),
                ("N6", "site_data"), ("N7", "_check_record"), ("N8", "load_plugins"))


# ================================================================ [K] 面变异（真跑子进程）
# [K] 组是 subprocess 真跑**磁盘上的**实现，内存副本变异对子进程无效。
# ⇒ [K] 面变异改成：把变异后的源码写进**临时目录**（不污染工作树），临时把 IMPL 指向它，
#   真跑该副本、收集转红的 K 断言。

_K_MUTATIONS = (
    # 关掉证据必填闸（它在 load_plugins 与 render_plugin 两处生效 ⇒ 单点关掉即可让坏记录落盘成功）。
    ("KN0 关证据必填闸（缺证据的记录也建站落盘）",
     "    if not isinstance(evs, list) or len(evs) < MIN_EVIDENCE:",
     "    if False:  # MUT-K", {"K6"}),
    # 复核者反证的原样复现：拆掉 plugins.json 的 try/except（坏 JSON 不再转成 DataError ⇒ 退出码 2 变 1）。
    # 注：只拆「绕过 load_plugins」是不够的——证据闸在 render_plugin 里还有第二道，故不作为变异项。
    ("KN1 拆掉 plugins.json 的坏 JSON fail-closed",
     "    try:\n"
     "        with open(ppath, encoding=\"utf-8\") as fh:\n"
     "            pdoc = json.load(fh)\n"
     "    except (OSError, ValueError) as exc:\n"
     "        raise DataError(f\"plugins.json 读取失败：{ppath}（{exc}）\")\n",
     "    with open(ppath, encoding=\"utf-8\") as fh:\n"
     "        pdoc = json.load(fh)  # MUT-K：坏 JSON 不再 fail-closed\n",
     {"K7"}),
    ("KN2 关渲染转义（真源文本直出页面）",
     "    return html.escape(str(text), quote=True)",
     "    return str(text)  # MUT-K", {"K4"}),
    ("KN3 注入生成时刻（破坏落盘确定性）",
     '    """确定性判据：不注入任何时刻信息。"""\n    return ""',
     '    """MUT-K：注入时刻。"""\n    return "<div>生成于 2026-10-13 00:00:00</div>"',
     {"K5"}),
    ("KN4 --print 也落盘（拆掉「只打印」的早退）",
     "    if print_only:\n"
     "        for name, text in pages:\n"
     "            sys.stdout.write(f\"===== {name} =====\\n{text}\")\n"
     "        return [name for name, _ in pages]\n",
     "    if print_only:\n"
     "        for name, text in pages:\n"
     "            sys.stdout.write(f\"===== {name} =====\\n{text}\")\n"
     "        # MUT-K：不再提前 return，继续落盘\n",
     {"K8"}),
    ("KN5 详情页丢「可复跑证据」段",
     "        \"<h2>可复跑证据（命令 ＋ 原始输出）</h2>\",",
     "        \"\",  # MUT-K：证据段落被删", {"K3"}),
    ("KN6 页面引外部资源（拆掉自包含）",
     "        f\"<title>{esc(title)} · 插件测评站</title>\",",
     "        f\"<title>{esc(title)} · 插件测评站</title>\",\n"
     "        '<img src=\"http://example.invalid/x.png\">',  # MUT-K：引入外部资源",
     {"K10"}),
    ("KN7 多产一页（页清单不再与真源一一对应）",
     "    pages.append((\"method.html\", render_method(method)))",
     "    pages.append((\"method.html\", render_method(method)))\n"
     "    pages.append((\"extra.html\", page(\"X\", \"index.html\", \"<p>x</p>\")))  # MUT-K",
     {"K2"}),
)


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
    """锚点自检：任一 [J] 锚点在当前实现里命中次数 ≠1 → ANCHOR-MISS（退出码 2）。"""
    bad = []
    for (name, _old, _new, _exp), (_mid, fn) in zip(_MUTATIONS, _MUT_TARGETS):
        src = inspect.getsource(getattr(rb, fn))
        if src.count(_old) != 1:
            bad.append((name, src.count(_old)))
    if not bad:
        return 0
    for name, n in bad:
        print(f"  ANCHOR-MISS {name}：锚点命中 {n} 次（期望 1）")
    print("  => 实现已漂移，[J] 变异表失效：退出码 2（fail-closed）")
    return 2


def _k_anchor_preflight(source):
    """锚点自检：任一 [K] 锚点在磁盘实现源码里命中次数 ≠1 → ANCHOR-MISS（退出码 2）。"""
    bad = []
    for name, old, _new, _exp in _K_MUTATIONS:
        if source.count(old) != 1:
            bad.append((name, source.count(old)))
    if not bad:
        return 0
    for name, n in bad:
        print(f"  ANCHOR-MISS {name}：锚点命中 {n} 次（期望 1）")
    print("  => 实现已漂移，[K] 变异表失效：退出码 2（fail-closed）")
    return 2


def _mutate_mode():
    global IMPL
    rc = _anchor_preflight()
    if rc:
        return rc
    source = io.open(IMPL, encoding="utf-8").read()
    krc = _k_anchor_preflight(source)
    if krc:
        return krc
    saved_impl = IMPL

    print("!! 定点变异自证：逐条短路一条映射，对应断言必须**恰好**转红\n")
    bad = []

    print("-- [J] 映射面（内存副本 exec；对应 J 断言） --")
    base_red = run_suite(quiet=True)
    print(f"  未变异基线（[J] 面）：红项 {len(base_red)} "
          f"{'（应为 0）' if not base_red else sorted(base_red)}")
    if base_red:
        bad.append(f"[J] 基线即转红：{sorted(base_red)}")
    for (name, old, new, expect), (_mid, fn) in zip(_MUTATIONS, _MUT_TARGETS):
        restore = _mut_source(fn, old, new)
        try:
            red = run_suite(quiet=True)
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

    print()
    print("-- [K] 落盘面（变异写临时源码副本 → 子进程真跑 → 对应 K 断言转红） --")
    print("   覆盖映射：KN0→K6 · KN1→K7 · KN2→K4 · KN3→K5 · KN4→K8 · KN5→K3 · KN6→K10 · KN7→K2")
    print("   未被专项变异的 K 断言：K1（happy-path 不变量——上面每条 K 变异下都必须保持绿）"
          "、K9（仓内真源路径，由默认模式的真跑覆盖）")
    kroot = tempfile.mkdtemp(prefix="review_site_kmut_")
    try:
        kbase = run_suite_k(os.path.join(kroot, "_baseline"))
        print(f"  未变异基线（[K] 面）：红项 {len(kbase)} "
              f"{'（应为 0）' if not kbase else sorted(kbase)}")
        if kbase:
            bad.append(f"[K] 基线即转红：{sorted(kbase)}")
        for name, old, new, expect in _K_MUTATIONS:
            d = os.path.join(kroot, name.split(" ", 1)[0])
            os.makedirs(d, exist_ok=True)
            mut = os.path.join(d, "review_build.py")
            with io.open(mut, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(source.replace(old, new))
            IMPL = mut
            try:
                red = run_suite_k(os.path.join(d, "work"))
            except Exception as exc:                              # noqa: BLE001
                red = {f"<变异体异常:{type(exc).__name__}>"}
            finally:
                IMPL = saved_impl
            hit = red == set(expect)
            if not hit:
                bad.append(f"{name}：红项 {sorted(red)} ≠ 期望 {sorted(expect)}")
            print(f"  {'[PASS]' if hit else '[FAIL]'} {name}：红项 {len(red)}"
                  f"（期望 {len(expect)}）"
                  + ("" if hit else f" 实={sorted(red)} 期={sorted(expect)}"))
    finally:
        IMPL = saved_impl
        shutil.rmtree(kroot, ignore_errors=True)

    print("\n定点变异：" + ("PASS（逐条恰好命中期望红项）" if not bad
                            else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--list" in argv:
        print(f"[J] 映射面变异（内存副本 exec）——{len(_MUTATIONS)} 条：")
        for name, _old, _new, exp in _MUTATIONS:
            print(f"  {name:<40} expect_red={len(exp)} {sorted(exp)}")
        print(f"[K] 落盘面变异（临时副本 ＋ 子进程真跑）——{len(_K_MUTATIONS)} 条：")
        for name, _old, _new, exp in _K_MUTATIONS:
            print(f"  {name:<40} expect_red={len(exp)} {sorted(exp)}")
        print(f"合计 {len(_MUTATIONS) + len(_K_MUTATIONS)} 条定点变异")
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
