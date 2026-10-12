# -*- coding: utf-8 -*-
"""插件测评站 · 静态站生成器（纯 Python 标准库；不触网、零第三方依赖）。

真源：`review/data/plugins.json`（测评记录）＋ `review/data/method.json`（方法说明）。
产物：`review/site/*.html`（首页 / 榜单 / 每插件一页详情 / 方法说明 —— ≥4 页）。

★ 一条硬口径（本仓守卫体例）：**证据＝命令字符串 ＋ 已采集的原始输出**。
生成器**不执行**这些命令——它只把字符串渲染进页面；读数的采集发生在写 JSON 之前，
CI 只跑本生成器与守卫，**不发起任何网络请求**（见 `import_allowlist`）。

离线口径
---------------------------------------------------------------
    python -X utf8 scripts/review_build.py                     # 生成到 review/site/
    python -X utf8 scripts/review_build.py --data review/data --out review/site
    python -X utf8 scripts/review_build.py --print             # 只打印不落盘

确定性：**输出不含生成时刻**（同真源 ⇒ 逐字节同一 HTML），便于守卫逐字节比对。
退出码：0 = 生成成功；2 = 输入/环境错误（JSON 坏、记录缺字段、页数/条目数不足——fail-closed）。
"""
from __future__ import annotations

import argparse
import ast
import copy
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # <仓根>/scripts
REPO = os.path.dirname(HERE)                               # <仓根>
IMPL = os.path.abspath(__file__)                           # 本文件（import 自检要读它）

#: 站点最少页数（首页 / 榜单 / 详情 / 方法）。
MIN_PAGES = 4

#: 最少测评条目数。
MIN_PLUGINS = 3

#: 最少证据条目数（每条 ≥1 条「命令 ＋ 原始输出」）。
MIN_EVIDENCE = 1

#: 名单里必须出现的三支测评对象（原任务固定）。
REQUIRED_PLUGIN_IDS = ("dsh-better-sidebar", "dsh-cost-meter", "dsh-office-tools")

#: 每条测评记录必须齐备的字段（缺一即坏输入）。
REQUIRED_PLUGIN_FIELDS = ("id", "name", "version", "version_source", "source_url",
                          "category", "dimensions", "evidence", "verdict", "boundaries")

#: 纯 stdlib 白名单之外**额外禁止**的模块（触网/起进程类；import 到即判坏）。
FORBIDDEN_IMPORTS = ("socket", "urllib", "urllib2", "http", "httplib", "requests",
                     "ftplib", "smtplib", "telnetlib", "asyncio", "subprocess",
                     "xmlrpc", "webbrowser", "ssl", "aiohttp")

#: 生成器允许 import 的模块白名单（纯 stdlib；零第三方依赖）。
STDLIB_ALLOWLIST = ("__future__", "argparse", "ast", "copy", "html", "json", "os", "sys",
                    "pathlib", "re", "typing", "collections", "textwrap")


class DataError(Exception):
    """输入数据/环境错误（fail-closed → 退出码 2）。"""


# ================================================================ 判据面（每条 = 一个可定点变异的函数）


# 生效条件：text 为任意值（含 JSON 真源里来的不可信文本）时返回其 HTML 转义形态（含引号）——真源内容进页面一律先过这里。
def esc(text) -> str:
    """HTML 转义（真源内容进页面前的唯一出口）。"""
    return html.escape(str(text), quote=True)


# 生效条件：无参数时返回本模块源码里出现过的**顶层模块名**集合——用于证「纯 stdlib、不触网」。
def import_names(source=None) -> set:
    """解析源码 AST，收集所有 import 的顶层模块名。"""
    if source is None:
        source = open(IMPL, encoding="utf-8").read()
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


# 生效条件：无参数时返回违反「纯 stdlib、不触网」的模块名列表（空列表 = 合规）。
def import_allowlist() -> list:
    """import 自检：白名单之外或额外禁止的模块 ⇒ 逐个点名。"""
    bad = []
    for name in sorted(import_names()):
        if name in FORBIDDEN_IMPORTS:
            bad.append(name)
        elif name not in STDLIB_ALLOWLIST:
            bad.append(name)
    return bad


# 生效条件：doc 为 plugins.json 解析结果时返回其 plugins 列表（去重要）；结构不符抛 DataError。
def plugin_list(doc) -> list:
    """从真源文档取条目列表（只认 ``{"plugins": [...]}``）。"""
    if not isinstance(doc, dict):
        raise DataError("plugins.json 顶层须为对象")
    plugins = doc.get("plugins")
    if not isinstance(plugins, list):
        raise DataError("plugins.json 缺 plugins 数组")
    if len(plugins) < MIN_PLUGINS:
        raise DataError(f"测评条目 {len(plugins)} 条 < {MIN_PLUGINS}（验收要求 ≥3 个插件）")
    out, seen = [], set()
    for rec in plugins:
        if not isinstance(rec, dict):
            raise DataError("plugins[] 每条须为对象")
        pid = str(rec.get("id") or "")
        if not pid:
            raise DataError("plugins[] 有条目缺 id")
        if pid in seen:
            raise DataError(f"插件 id 重复：{pid}")
        seen.add(pid)
        out.append(rec)
    return out


# 生效条件：rec 为一条测评记录时返回其中证据列表（每条须带 command 与 output）；缺字段抛 DataError。
def evidence_of(rec) -> list:
    """取一条记录的证据列表（结构不对就响亮失败）。"""
    evs = rec.get("evidence")
    if not isinstance(evs, list) or len(evs) < MIN_EVIDENCE:
        raise DataError(f"{rec.get('id')}：证据 {len(evs) if isinstance(evs, list) else 0} 条"
                        f"（每条测评记录须 ≥1 条「命令 ＋ 原始输出」）")
    for ev in evs:
        if not isinstance(ev, dict):
            raise DataError(f"{rec.get('id')}：证据条目须为对象")
        if not str(ev.get("command") or "").strip():
            raise DataError(f"{rec.get('id')}：证据缺 command")
        if not str(ev.get("output") or "").strip():
            raise DataError(f"{rec.get('id')}：证据缺 output（原始输出）")
    return evs


# 生效条件：rec 为一条测评记录时校验五维读数与结论/边界齐备；不齐抛 DataError。
def _check_record(rec) -> None:
    pid = str(rec.get("id") or "")
    for field in REQUIRED_PLUGIN_FIELDS:
        if field not in rec:
            raise DataError(f"{pid}：缺字段 {field}")
    for field in ("id", "name", "version", "version_source", "source_url",
                  "category", "verdict"):
        if not str(rec.get(field) or "").strip():
            raise DataError(f"{pid}：字段 {field} 为空")
    if not str(rec.get("source_url") or "").startswith("http"):
        raise DataError(f"{pid}：source_url 非 http(s)：{rec.get('source_url')!r}")
    dims = rec.get("dimensions")
    if not isinstance(dims, list) or not dims:
        raise DataError(f"{pid}：dimensions 须为非空数组（验收要求含测评维度）")
    for dim in dims:
        if not isinstance(dim, dict) or not str(dim.get("name") or "").strip():
            raise DataError(f"{pid}：维度缺 name")
        if not (str(dim.get("finding") or "").strip() or str(dim.get("basis") or "").strip()):
            raise DataError(f"{pid}：维度 {dim.get('name')} 缺 finding/basis")
    if not isinstance(rec.get("boundaries"), list) or not rec["boundaries"]:
        raise DataError(f"{pid}：boundaries 须为非空数组（验收要求含边界）")


# 生效条件：doc 为 plugins.json 解析结果时返回插件记录列表（每条过 _check_record 与 evidence_of）；违规抛 DataError。
def load_plugins(doc) -> list:
    """校验并返回条目列表（结构坏了就 fail-closed，不静默跳过）。"""
    out = plugin_list(doc)
    for rec in out:
        _check_record(rec)
        evidence_of(rec)
    missing = [pid for pid in REQUIRED_PLUGIN_IDS
               if pid not in {str(r.get("id")) for r in out}]
    if missing:
        raise DataError("固定测评对象缺席：" + "，".join(missing))
    return out


# 生效条件：path 为 review/data/plugins.json 路径时返回校验后的条目列表；文件/JSON 坏抛 DataError。
def load_data(data_dir) -> dict:
    """读真源目录（plugins.json ＋ method.json），返回 {'plugins': [...], 'method': {...}}。"""
    ppath = os.path.join(data_dir, "plugins.json")
    mpath = os.path.join(data_dir, "method.json")
    try:
        with open(ppath, encoding="utf-8") as fh:
            pdoc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise DataError(f"plugins.json 读取失败：{ppath}（{exc}）")
    try:
        with open(mpath, encoding="utf-8") as fh:
            mdoc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise DataError(f"method.json 读取失败：{mpath}（{exc}）")
    if not isinstance(mdoc, dict):
        raise DataError("method.json 顶层须为对象")
    return {"plugins": load_plugins(pdoc), "method": mdoc}


# 生效条件：rec 为一条记录时返回 (模型工具面 ≈tok/轮, 证据条数)——读不到 tok 记 None（排最后），不拿 0 冒充。
def score_of(rec) -> tuple:
    """排序用的正交读数：模型工具面成本（可空）＋ 证据条数。"""
    token = rec.get("tool_tokens")
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), list) else []
    if isinstance(token, (int, float)) and not isinstance(token, bool):
        return (0, float(token), len(ev))
    return (1, 0.0, len(ev))


# 生效条件：rec 为一条记录时返回榜单排序键（可核验成本升序 → 读不到者靠后 → 证据条数升序 → id 字典序）。
def _sort_key(rec):
    return score_of(rec) + (str(rec.get("id") or ""),)


# 生效条件：plugins 为记录列表时返回按 _sort_key 升序的**新**列表（不改入参）。
def rank_plugins(plugins) -> list:
    """多读数并列榜（不合成加权总分——权重归使用者）。"""
    return sorted(plugins, key=_sort_key)


# 生效条件：pid 为插件 id 时返回详情页文件名（`plugin-<slug>.html`；非字母数字折叠成 `-`）。
def slugify(pid) -> str:
    """插件 id → 文件名 slug。"""
    out = []
    for ch in str(pid):
        out.append(ch.lower() if ch.isalnum() else "-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "plugin"


# 生效条件：pid 为插件 id 时返回其详情页文件名。
def detail_file(pid) -> str:
    """`plugin-<slug>.html`。"""
    return f"plugin-{slugify(pid)}.html"


# 生效条件：无参数时返回 Markdown 围栏展开用的**零信息**分隔线（确定性：输出不含生成时刻）。
def _now_stamp() -> str:
    """确定性判据：不注入任何时刻信息。"""
    return ""


# 生效条件：plugins 为记录列表、method 为方法说明对象时返回站点页清单 [(文件名, 页面 HTML)]；违反页数/条目数下限抛 DataError。
def site_data(plugins, method) -> list:
    """生成整站页清单（含下限自检——不足即 fail-closed）。"""
    pages = [("index.html", render_index(plugins, method))]
    pages.append(("ranking.html", render_ranking(plugins, method)))
    for rec in plugins:
        pages.append((detail_file(rec["id"]), render_plugin(rec, method)))
    pages.append(("method.html", render_method(method)))
    if len(pages) < MIN_PAGES:
        raise DataError(f"产出 {len(pages)} 页 < {MIN_PAGES}（验收要求 ≥4 页）")
    if len(plugins) < MIN_PLUGINS:
        raise DataError(f"详情页 {len(plugins)} 个 < {MIN_PLUGINS}（验收要求 ≥3 个插件）")
    return pages


# ================================================================ HTML 外壳与各页


# 生效条件：title/active/body 给定时返回整页 HTML（内联 CSS、无外部资源、UTF-8）；active 为当前页文件名（导航高亮）。
def page(title, active, body) -> str:
    nav = (("index.html", "首页"), ("ranking.html", "榜单"), ("method.html", "方法说明"))
    links = "".join(
        f'<a class="{"on" if fn == active else ""}" href="{fn}">{name}</a>'
        for fn, name in nav)
    return "\n".join([
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(title)} · 插件测评站</title>",
        "<style>",
        CSS,
        "</style>",
        "</head>",
        "<body>",
        '<header><h1><a href="index.html">插件测评站</a></h1>'
        f"<nav>{links}</nav></header>",
        "<main>",
        body,
        _now_stamp(),
        "</main>",
        '<footer>本页由 <code>scripts/review_build.py</code> 从 '
        '<code>review/data/plugins.json</code> ＋ <code>review/data/method.json</code> '
        '机械生成——勿手改。证据＝命令 ＋ 已采集的原始输出；生成器与 CI <b>不触网</b>。</footer>',
        "</body>",
        "</html>",
        "",
    ])


CSS = """\
:root{--fg:#1c1e21;--dim:#606770;--line:#e4e6eb;--acc:#1d76db;--bg:#fff;--soft:#f5f6f7}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);line-height:1.7;
 font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{border-bottom:1px solid var(--line);padding:18px 24px;background:var(--soft)}
header h1{margin:0 0 8px;font-size:20px}
header h1 a{color:var(--fg);text-decoration:none}
nav a{margin-right:16px;color:var(--dim);text-decoration:none;font-size:15px}
nav a.on{color:var(--acc);font-weight:700;border-bottom:2px solid var(--acc)}
main{max-width:900px;margin:0 auto;padding:24px}
h2{font-size:18px;margin:28px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:20px 0 6px}
table{width:100%;border-collapse:collapse;margin:10px 0;font-size:14px}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:var(--soft)}
code{background:var(--soft);padding:1px 5px;border-radius:3px;font-size:13px}
pre{background:var(--soft);padding:12px;border-radius:5px;overflow:auto;font-size:13px}
.note{background:#fff8e1;border-left:4px solid #f0ad4e;padding:10px 14px;margin:14px 0}
.ok{background:#eef7ee;border-left:4px solid #4caf50;padding:10px 14px;margin:14px 0}
.muted{color:var(--dim)}
.tag{display:inline-block;background:var(--soft);border:1px solid var(--line);
 border-radius:10px;padding:0 8px;font-size:12px;margin-right:6px}
.bar{display:inline-block;height:10px;background:var(--acc);border-radius:2px;vertical-align:middle}
footer{border-top:1px solid var(--line);margin-top:36px;padding:16px 24px;
 color:var(--dim);font-size:13px}
"""


# 生效条件：plugins/method 给定时返回首页 HTML（这是什么／证据字段／维度／三插件速览／边界／怎么复跑）。
def render_index(plugins, method) -> str:
    fields = "".join(f"<tr><td><code>{esc(f.get('field'))}</code></td>"
                     f"<td>{esc(f.get('meaning'))}</td></tr>"
                     for f in method.get("evidence_fields") or ())
    dims = "".join(f"<tr><td><b>{esc(d.get('name'))}</b></td><td>{esc(d.get('check'))}</td>"
                   f"<td>{esc(d.get('why'))}</td></tr>" for d in method.get("dimensions") or ())
    rows = "".join(
        f"<tr><td><a href=\"{esc(detail_file(r['id']))}\">{esc(r['name'])}</a></td>"
        f"<td>{esc(r['version'])}</td><td>{esc(r['category'])}</td>"
        f"<td>{len(r.get('dimensions') or ())}</td>"
        f"<td>{len(r.get('evidence') or ())}</td>"
        f"<td>{esc(r['verdict'][:60])}</td></tr>" for r in rank_plugins(plugins))
    bounds = "".join(f"<li>{esc(b)}</li>" for b in method.get("boundaries") or ())
    rerun = "".join(f"<li><code>{esc(c)}</code></li>" for c in method.get("rerun") or ())
    body = "\n".join([
        f"<h2>这是什么</h2>",
        f"<p>{esc(method.get('intro'))}</p>",
        '<div class="note"><b>证据＝命令 ＋ 已采集的原始输出</b>——生成器<b>不执行</b>这些命令，'
        "页面上的读数都在写进 JSON 之前就采集完毕（CI 不触网）。</div>",
        "<h2>四个证据字段</h2>",
        '<table><tr><th>字段</th><th>含义</th></tr>' + fields + "</table>",
        "<h2>五个测评维度</h2>",
        '<table><tr><th>维度</th><th>查什么</th><th>为什么</th></tr>' + dims + "</table>",
        "<h2>三插件速览（点名字进详情）</h2>",
        '<table><tr><th>插件</th><th>版本</th><th>类别</th><th>维度</th><th>证据</th>'
        "<th>结论（截断）</th></tr>" + rows + "</table>",
        "<h2>两条诚实边界（先读这个）</h2>",
        f"<ul>{bounds}</ul>",
        "<h2>怎么复跑</h2>",
        f"<ol>{rerun}</ol>",
        '<p class="muted">榜单页只做多读数并列、<b>不合成加权总分</b>——权重归使用者，'
        "<a href=\"ranking.html\">去榜单</a> ｜ <a href=\"method.html\">读方法说明</a></p>",
        "",
    ])
    return page("首页", "index.html", body)


# 生效条件：plugins/method 给定时返回榜单 HTML（多读数并列，不合成总分；名次＝排序键序）。
def render_ranking(plugins, method) -> str:
    rows = rank_plugins(plugins)
    peak = max([float(r.get("tool_tokens") or 0) for r in rows] + [1.0])
    trs = []
    for i, r in enumerate(rows, 1):
        tok = r.get("tool_tokens")
        if isinstance(tok, (int, float)) and not isinstance(tok, bool):
            width = int(round(120 * float(tok) / peak))
            cell = (f"{int(tok)} <span class=\"bar\" style=\"width:{width}px\"></span>")
        else:
            cell = '<span class="muted">读不到（不参与）</span>'
        src = str(r.get("version_source") or "")
        trs.append(f"<tr><td>{i}</td>"
                   f"<td><a href=\"{esc(detail_file(r['id']))}\">{esc(r['name'])}</a></td>"
                   f"<td>{esc(r['version'])}</td><td>{cell}</td>"
                   f"<td>{len(r.get('evidence') or ())}</td>"
                   f"<td>{len(r.get('boundaries') or ())}</td>"
                   f"<td>{esc(src[:70])}</td></tr>")
    body = "\n".join([
        "<h2>榜单 · 多读数并列</h2>",
        f'<div class="note">排序规则：{esc(method.get("ranking_rule"))}</div>',
        '<table><tr><th>名次</th><th>插件</th><th>版本</th>'
        "<th>模型工具面 ≈tok/轮</th><th>证据条数</th><th>边界条数</th>"
        "<th>版本出处（截断）</th></tr>" + "".join(trs) + "</table>",
        '<p class="muted">「读不到（不参与）」＝该包不注册模型工具或不在此工具面里——'
        "这是数据缺口，<b>不是 0 成本</b>。</p>",
        "",
    ])
    return page("榜单", "ranking.html", body)


# 生效条件：rec 为一条测评记录、method 为方法说明对象时返回该插件的详情页 HTML（版本出处／维度读数／证据／结论／边界）。
def render_plugin(rec, method) -> str:
    dims = "".join(
        f"<tr><td><b>{esc(d.get('name'))}</b></td><td>{esc(d.get('finding'))}</td>"
        f"<td class=\"muted\">{esc(d.get('basis'))}</td></tr>"
        for d in rec.get("dimensions") or ())
    evs = []
    for i, ev in enumerate(evidence_of(rec), 1):
        evs.append(f"<h3>证据 {i}</h3>"
                   f"<p>命令：<code>{esc(ev.get('command'))}</code></p>"
                   f"<pre>{esc(ev.get('output'))}</pre>"
                   f"<p class=\"muted\">出处：{esc(ev.get('source'))}"
                   + (f" ｜ 采集：{esc(ev.get('captured_at'))}" if ev.get("captured_at") else "")
                   + "</p>")
    bounds = "".join(f"<li>{esc(b)}</li>" for b in rec.get("boundaries") or ())
    body = "\n".join([
        f"<h2>{esc(rec['name'])} @ {esc(rec['version'])}</h2>",
        f"<p><span class=\"tag\">{esc(rec['category'])}</span>"
        f'<a href="{esc(rec["source_url"])}">{esc(rec["source_url"])}</a></p>',
        f'<div class="note"><b>版本出处</b>：{esc(rec["version_source"])}'
        "——版本号现取，不凭记忆。</div>",
        "<h2>维度读数</h2>",
        '<table><tr><th>维度</th><th>读数</th><th>依据</th></tr>' + dims + "</table>",
        "<h2>可复跑证据（命令 ＋ 原始输出）</h2>",
        *evs,
        "<h2>结论</h2>",
        f'<div class="ok">{esc(rec["verdict"])}</div>',
        "<h2>边界（本站不知道什么）</h2>",
        f"<ul>{bounds}</ul>",
        '<p class="muted">返回 <a href="index.html">首页</a> ｜ '
        '<a href="ranking.html">榜单</a> ｜ <a href="method.html">方法说明</a></p>',
        "",
    ])
    return page(f"{rec['name']} @ {rec['version']}", detail_file(rec["id"]), body)


# 生效条件：method 为方法说明对象时返回方法说明页 HTML（字段／维度／排序规则／离线口径／边界／复跑）。
def render_method(method) -> str:
    fields = "".join(f"<tr><td><code>{esc(f.get('field'))}</code></td>"
                     f"<td>{esc(f.get('meaning'))}</td></tr>"
                     for f in method.get("evidence_fields") or ())
    dims = "".join(f"<tr><td><b>{esc(d.get('name'))}</b></td><td>{esc(d.get('check'))}</td>"
                   f"<td>{esc(d.get('why'))}</td></tr>" for d in method.get("dimensions") or ())
    pages = "".join(f"<tr><td><code>{esc(p.get('file'))}</code></td>"
                    f"<td>{esc(p.get('content'))}</td></tr>" for p in method.get("pages") or ())
    off = "".join(f"<li>{esc(x)}</li>" for x in method.get("offline") or ())
    bounds = "".join(f"<li>{esc(x)}</li>" for x in method.get("boundaries") or ())
    rerun = "".join(f"<li><code>{esc(x)}</code></li>" for x in method.get("rerun") or ())
    sections = "".join(f"<li>{esc(x)}</li>" for x in
                       (method.get("declaration_template") or {}).get("sections") or ())
    body = "\n".join([
        f"<h2>{esc(method.get('title'))}</h2>",
        f"<p>{esc(method.get('subtitle'))}</p>",
        "<h2>四个证据字段</h2>",
        '<table><tr><th>字段</th><th>含义</th></tr>' + fields + "</table>",
        "<h2>五个测评维度</h2>",
        '<table><tr><th>维度</th><th>查什么</th><th>为什么</th></tr>' + dims + "</table>",
        "<h2>排序规则</h2>",
        f"<p>{esc(method.get('ranking_rule'))}</p>",
        "<h2>页面结构</h2>",
        '<table><tr><th>页面</th><th>内容</th></tr>' + pages + "</table>",
        "<h2>离线口径（零网络）</h2>",
        f"<ul>{off}</ul>",
        "<h2>本站不假装知道什么（边界）</h2>",
        f"<ul>{bounds}</ul>",
        "<h2>交付体例（骨架）</h2>",
        f"<ol>{sections}</ol>",
        "<h2>怎么复跑</h2>",
        f"<ol>{rerun}</ol>",
        f'<p class="muted">{esc(method.get("generated_note"))}</p>',
        "",
    ])
    return page("方法说明", "method.html", body)


# ================================================================ 生成入口


# 生效条件：data_dir 为真源目录、out_dir 为输出目录、print_only 为假时把各页写盘；返回落盘文件名列表（print_only 为真时不写盘）。
def build(data_dir, out_dir, print_only=False) -> list:
    """从 review/data/ 生成整站；返回落盘的文件名列表。"""
    data = load_data(data_dir)
    pages = site_data(data["plugins"], data["method"])
    if print_only:
        for name, text in pages:
            sys.stdout.write(f"===== {name} =====\n{text}")
        return [name for name, _ in pages]
    os.makedirs(out_dir, exist_ok=True)
    made = []
    for name, text in pages:
        with open(os.path.join(out_dir, name), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(text)
        made.append(name)
    if len(made) < MIN_PAGES:
        raise DataError(f"落盘 {len(made)} 页 < {MIN_PAGES}")
    return made


# 生效条件：argv 为命令行参数列表（None = sys.argv[1:]）时生成站点并返回退出码——0 成功 / 2 输入或环境错误。
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="插件测评站 · 静态站生成器（纯 stdlib；从 review/data/ 机械生成）")
    ap.add_argument("--data", default=os.path.join("review", "data"),
                    help="真源目录（默认 review/data）")
    ap.add_argument("--out", default=os.path.join("review", "site"),
                    help="输出目录（默认 review/site）")
    ap.add_argument("--print", dest="print_only", action="store_true",
                    help="只打印不落盘")
    args = ap.parse_args(argv)
    try:
        made = build(args.data, args.out, print_only=args.print_only)
        data = load_data(args.data)
        if args.print_only:
            print(f"（--print：{len(made)} 页未落盘；条目 "
                  f"{len(data['plugins'])} 个）")
        else:
            print(f"站点已生成：{args.out}/（{', '.join(made)}；条目 "
                  f"{len(data['plugins'])} 个）")
        return 0
    except DataError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
