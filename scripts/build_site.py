# -*- coding: utf-8 -*-
"""灵枢悬赏站 · 静态站生成器（纯 Python 标准库；不触网、不装依赖）。

设计稿：`docs/spec/悬赏板设计_v0.1.md`（v0.1，2026-10-09）。
状态机／账本口径真源：`scripts/bounty_board.py`（**本文件不重造计分**——直接复用
其 `score_board`／`load_ledger`，防两处口径漂移）。

四页（中文界面）：
    index.html   首页——这是什么／怎么认领／怎么交付／去哪看规则
    board.html   悬赏板——当前**可认领**任务（从账本推演，或读 `--tasks` 快照）
    honor.html   荣誉榜——**由账本机械生成**（分数从 delta 求和，不接受手写）
    rules.html   规则页——认领-租约-验收四闸-声誉计分

一条硬口径（设计稿 §五）：**结算＝声誉制，不涉资金**——本站只显示声誉分，
页面里没有任何支付/钱包/链上概念，也没有任何资金字段可填。

★ 计分数值（easy 1 / medium 3 / hard 6 / expert 10；虚假交付 −5；超时 −1）在设计稿
  的口径（v1.0 质量化）——每一处出现分值/口径处都带 `NOTE_PENDING`
  标注（"数值待设计者裁"），不许写成已定。

离线口径（**本站生成器恒不触网**）
---------------------------------------------------------------
    # 从账本生成到 site/（默认）
    python -X utf8 scripts/build_site.py

    # 指定账本与输出目录
    python -X utf8 scripts/build_site.py --ledger docs/bounty/ledger.json --out site

    # 悬赏板改读 issue 面快照（由 `gh issue list --json …` 之类的产物喂进来；
    # 本生成器自己不联网、不调 gh）
    python -X utf8 scripts/build_site.py --tasks docs/bounty/tasks.json

    # 只打印不落盘（本地核验用）
    python -X utf8 scripts/build_site.py --print

确定性：**输出不含生成时刻**（同一账本 ⇒ 逐字节同一 HTML），便于守卫逐字节比对。

退出码：0 = 生成成功；2 = 输入/环境错误（账本坏 JSON、tasks 结构不符——fail-closed）。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # <仓根>/scripts
REPO = os.path.dirname(HERE)                               # <仓根>
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bounty_board as bb                                            # noqa: E402

#: 可认领态（设计稿 §三；`expired` 在 MVP 不驻留，但作为「回板窗口」仍算可认领）。
CLAIMABLE = ("open", "expired")

#: 难度显示序（悬赏板按此升序排：越难的越靠后；未知难度排最后）。
DIFFICULTY_ORDER = {"difficulty:easy": 0, "difficulty:medium": 1,
                    "difficulty:hard": 2, "difficulty:expert": 3}

#: 难度显示名。
DIFFICULTY_LABEL = {"difficulty:easy": "easy", "difficulty:medium": "medium",
                    "difficulty:hard": "hard", "difficulty:expert": "expert"}

#: ★ 计分数值在设计稿里是「建议值，待裁」——出现分值的页面一律带这句。
NOTE_PENDING = ("计分口径已定（v1.0 质量化；依据《质量化计分标准与方式 v1.0》）；"
                "改口径只改 scripts/bounty_board.py 的 DIFFICULTY_SCORES 与 "
                "quality_delta ／ timeout_delta ／ invalid_delta。")

#: 计分口径说明（页面用；分数本身从账本 delta 求和，不手写）。
SCORE_RULE = ("完成分（质量化）：max(1, round_half_up(base × 2/(round+1)))——"
              "base = easy 1 ／ medium 3 ／ hard 6 ／ expert 10；round = 已发生返工次数（首交付 0），"
              "故首交付 2×、中性点（返工 1 次）1×、返工 2 次 2/3；"
              "扣分：超时未交付 −2×base ／ 轮次用尽判无效交付 −base（**退回返工不扣分**）；"
              "主动释放与争议提起不扣分（争议败诉记录在案、不扣本金）；被拒命令记 0 分但记在尝试者头上。"
              "本承载面不适用：验收条目通过率 E（无承载 ⇒ E≡1）、落选分（无竞标机制）。"
              "账本按 rule 分段生效：v0.1 旧事件用固定分（虚假交付 −5／超时 −1），v1.0 起用质量化。")

#: 验收四闸（设计稿 §四；第 4 闸是**人审**，不得写成自动通过）。
ACCEPTANCE_GATES = (
    ("① CI 全绿", "该 PR 上本仓门禁全绿——机器判，不可辩。"),
    ("② 复现读数", "可复现缺陷类须贴原始读数（改前 vs 改后逐项对照）。"),
    ("③ 守卫＋定点变异", "修码类必须带守卫件，以及「注入必失败 ⇒ 断言必红并点名」的定点变异自证。"),
    ("④ 维护者人审", "维护者 `/verify` 给出判定与理由——**这一闸是人审，不是自动通过**。"),
)

#: 命令面（设计稿 §三；只认「行首最前的词」）。
COMMAND_ROWS = (
    ("/claim", "任何人", "无锁 ∧ `bounty` 标签在 ∧ 态 open/expired ∧ 本人并发 ≤ 2",
     "上锁 ＋ 记到期时间（72h）"),
    ("/deliver <PR 链接或证据块>", "认领者", "仅认领人 ∧ 必带链接或证据块 ∧ 轮次 ≤ 3",
     "转 `bounty:delivered`，等验收；**轮次用尽 ⇒ 判无效交付**（转 `disputed`、记 −base）"),
    ("/withdraw", "认领者", "仅认领人", "主动释放、任务回板（**不影响声誉**）"),
    ("/dispute <理由>", "双方", "必带理由 ∧ 属当事人", "转 `bounty:disputed`，维护者仲裁留痕"),
    ("/verify [pass|fail] <理由>", "维护者", "态为 `delivered`",
     "通过 ⇒ `verified`；不通过 ⇒ **不扣分**、退回返工（轮次照计）"),
    ("/settle", "维护者", "态为 `verified`", "按 `difficulty:*` 记正分入账本"),
)


# ================================================================ 判据面（每条 = 一个可定点变异的函数）


# 生效条件：text 为任意值（含账本里来的不可信文本）时返回其 HTML 转义形态——账本内容一律先转义再进页面，防注入。
def esc(text) -> str:
    """HTML 转义（账本内容进页面前的唯一出口）。"""
    return html.escape(str(text), quote=True)


# 生效条件：flag 为真时返回 NOTE_PENDING（计分口径标注），为假时返回空串；页面凡出现分值/口径处调用它。
def _note_pending(flag=True) -> str:
    """分值标注判据：未裁定前，凡出现分值的页面必须带「待裁」标注。"""
    if not flag:
        return ""
    return NOTE_PENDING


# 生效条件：events 为账本事件列表时返回 {issue 号: 该 issue 的**最后一条**事件}——账本是 append-only 时序流，最后一条即当前态。
def latest_by_issue(events) -> dict:
    """账本 → 每 issue 的当前态（取最后一条事件）。"""
    out = {}
    for ev in events or []:
        num = ev.get("issue")
        if num is None:
            continue
        out[str(num)] = ev
    return out


# 生效条件：rec 为 open_tasks 记录时返回排序键（难度序升序，同难度按号）——悬赏板版面次序的唯一判据。
def _task_sort_key(rec):
    return (DIFFICULTY_ORDER.get("difficulty:" + rec["difficulty"], 99), rec["number"])


# 生效条件：row 为 score_board 视图行时返回榜面排序键（分数降序、登录名升序）——荣誉榜名次次序的唯一判据。
def _rank_key(row):
    return (-row["score"], row["login"])


# 生效条件：events 为账本事件列表、tasks 为可选的 issue 面快照（None 时从账本推演）时返回**可认领**任务列表，按难度序（同难度按号）排；只列态 ∈ CLAIMABLE 者。
def open_tasks(events, tasks=None) -> list:
    """当前可认领任务（issue 面快照优先；否则从账本推演当前态）。"""
    recs = []
    if tasks is not None:
        for t in tasks or ():
            recs.append({"number": str(t.get("number") or ""),
                         "title": str(t.get("title") or ""),
                         "difficulty": str(t.get("difficulty") or ""),
                         "state": str(t.get("state") or "").split(":")[-1],
                         "holder": str(t.get("holder") or ""),
                         "url": str(t.get("url") or "")})
    else:
        for num, ev in latest_by_issue(events).items():
            recs.append({"number": num, "title": "", 
                         "difficulty": str(ev.get("difficulty") or ""),
                         "state": str(ev.get("to") or ""),
                         "holder": str(ev.get("holder") or ""), "url": ""})
    out = []
    for rec in recs:
        if rec["state"] not in CLAIMABLE:
            continue
        rec["difficulty_label"] = DIFFICULTY_LABEL.get(
            "difficulty:" + rec["difficulty"], rec["difficulty"] or "未标")
        out.append(rec)
    return sorted(out, key=_task_sort_key)


# 生效条件：events 为账本事件列表时返回声誉榜行列表（分数＝delta 求和，**从账本算、不接受手写**），按「分数降序、登录名升序」排。
def leaderboard(events) -> list:
    """账本 → 声誉榜（复用状态机的 score_board，口径单点）。"""
    rows = bb.score_board(events).values()
    return sorted(rows, key=_rank_key)


# ================================================================ HTML 外壳与四页


# 生效条件：title/active/body 给定时返回整页 HTML（内联 CSS、无外部资源、UTF-8）；active 为当前页文件名（导航高亮）。
def page(title, active, body) -> str:
    nav = (("index.html", "首页"), ("board.html", "悬赏板"),
           ("honor.html", "荣誉榜"), ("rules.html", "规则"))
    links = "".join(
        f'<a class="{"on" if fn == active else ""}" href="{fn}">{name}</a>'
        for fn, name in nav)
    return "\n".join([
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(title)} · 灵枢悬赏站</title>",
        "<style>",
        CSS,
        "</style>",
        "</head>",
        "<body>",
        '<header><h1><a href="index.html">灵枢悬赏站</a></h1>',
        f'<nav>{links}</nav></header>',
        '<main>',
        body,
        "</main>",
        '<footer>本页由 <code>scripts/build_site.py</code> 从 '
        '<code>docs/bounty/ledger.json</code> 机械生成——勿手改。'
        '结算＝声誉制，<b>不涉资金</b>。</footer>',
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
main{max-width:880px;margin:0 auto;padding:24px}
h2{font-size:18px;margin:28px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:20px 0 6px}
table{width:100%;border-collapse:collapse;margin:10px 0;font-size:14px}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:var(--soft)}
code{background:var(--soft);padding:1px 5px;border-radius:3px;font-size:13px}
pre{background:var(--soft);padding:12px;border-radius:5px;overflow:auto}
.note{background:#fff8e1;border-left:4px solid #f0ad4e;padding:10px 14px;margin:14px 0}
.muted{color:var(--dim)}
.tag{display:inline-block;background:var(--soft);border:1px solid var(--line);
 border-radius:10px;padding:0 8px;font-size:12px;margin-right:6px}
footer{border-top:1px solid var(--line);margin-top:36px;padding:16px 24px;
 color:var(--dim);font-size:13px}
"""


# 生效条件：events 为账本事件列表时返回首页 HTML（这是什么／怎么认领／怎么交付／去哪看规则）。
def render_index(events) -> str:
    rows = "".join(f"<tr><td><code>{esc(c)}</code></td><td>{esc(who)}</td>"
                   f"<td>{esc(chk)}</td><td>{esc(eff)}</td></tr>"
                   for c, who, chk, eff in COMMAND_ROWS)
    body = "\n".join([
        "<h2>这是什么</h2>",
        "<p>把本仓的 issue 池变成<b>可认领的悬赏任务</b>：外部人或 AI agent 认领 → 交付 → "
        "过<b>验收四闸</b> → 记入<b>可追溯的声誉账本</b>。</p>",
        f'<div class="note"><b>不涉资金</b>：结算是声誉制（可查、可降、可追溯），'
        f'不是钱。{esc(_note_pending())}</div>',
        "<h2>怎么认领</h2>",
        "<ol>",
        "<li>在标了 <code>bounty</code> 且态为 <code>bounty:open</code> 的 issue 下评论 "
        "<code>/claim</code>——命令必须是评论首个非空行的第一个词。</li>",
        "<li>上锁成功即持有，租约 <b>72 小时</b>；同一人并发认领上限 <b>2</b>。</li>",
        "<li>认领前先读该 issue 的<b>验收标准</b>——我们只按那份判。</li>",
        "</ol>",
        "<h2>怎么交付</h2>",
        "<p>评论 <code>/deliver &lt;PR 链接或证据块&gt;</code>：修码类走 PR，"
        "分析／复现类走围栏代码块里的可复跑读数。最多 <b>3 轮</b>修改，"
        "超时自动回板（记 −1）。</p>",
        "<p>放弃用 <code>/withdraw</code>（不影响声誉）；有异议用 "
        "<code>/dispute &lt;理由&gt;</code>。</p>",
        "<h2>命令面</h2>",
        '<table><tr><th>命令</th><th>谁用</th><th>校验</th><th>效果</th></tr>',
        rows, "</table>",
        '<p class="muted">命令<b>只认行首最前的词</b>；被拒命令记在<b>尝试者</b>头上'
        "（刷单／重复认领可查）。</p>",
        "<h2>下一步</h2>",
        '<p><a href="board.html">去悬赏板看当前开放任务</a> ｜ '
        '<a href="honor.html">去荣誉榜看声誉账本</a> ｜ '
        '<a href="rules.html">读完整规则</a></p>',
        "",
    ])
    return page("首页", "index.html", body)


# 生效条件：events 为账本事件列表、tasks 为可选的 issue 面快照时返回悬赏板 HTML（只列可认领任务，按难度序）。
def render_board(events, tasks=None) -> str:
    items = open_tasks(events, tasks)
    if items:
        trs = []
        for r in items:
            title = esc(r["title"]) or '<span class="muted">（见 issue 标题）</span>'
            holder = ("@" + esc(r["holder"])) if r["holder"] else "—"
            trs.append(f"<tr><td>#{esc(r['number'])}</td><td>{title}</td>"
                       f"<td>{esc(r['difficulty_label'])}</td>"
                       f"<td>{esc(r['state'])}</td><td>{holder}</td></tr>")
        table = ("<table><tr><th>#</th><th>任务</th><th>难度</th><th>态</th>"
                 "<th>持有者</th></tr>" + "".join(trs) + "</table>")
    else:
        table = ('<p class="muted">（当前没有可认领的悬赏——账本里没有 '
                 "`open` 态的任务；维护者打 `bounty` 标签并发布后此处自动出现。）</p>")
    body = "\n".join([
        "<h2>悬赏板 · 当前开放任务</h2>",
        '<div class="note">' + esc(_note_pending()) + "</div>",
        "<p>下表<b>从账本推演</b>（每 issue 取最后一条事件为当前态），"
        "只列可认领（<code>open</code>／<code>expired</code>）者，按难度升序排。</p>",
        table,
        "<h2>怎么接</h2>",
        "<p>在对应 issue 下评论 <code>/claim</code>（行首最前的词）。"
        "规则与验收口径见 <a href=\"rules.html\">规则页</a>。</p>",
        "",
    ])
    return page("悬赏板", "board.html", body)


# 生效条件：events 为账本事件列表时返回荣誉榜 HTML（行由 leaderboard 从账本算出；空账本给「暂无入账」形态）。
def render_honor(events) -> str:
    rows = leaderboard(events)
    until = max((e.get("ts") or "" for e in events or ()), default="")
    if rows:
        trs = "".join(
            f"<tr><td>@{esc(r['login'])}</td><td><b>{r['score']}</b></td>"
            f"<td>{r['settled']}</td><td>{r['delivered']}</td>"
            f"<td>{r['timeouts']}</td><td>{r['disputes']}</td>"
            f"<td>{r['rejects']}</td><td>{esc(r['first'] or '—')}</td>"
            f"<td>{esc(r['last'] or '—')}</td></tr>" for r in rows)
        table = ("<table><tr><th>贡献者</th><th>声誉分</th><th>已结算</th>"
                 "<th>已交付</th><th>超时回板</th><th>争议</th><th>被拒命令</th>"
                 "<th>首次活动</th><th>最近活动</th></tr>" + trs + "</table>")
    else:
        table = ('<p class="muted">（暂无入账事件——账本为空；第一条 '
                 "`/settle` 落账后本表自动出现。）</p>")
    body = "\n".join([
        "<h2>荣誉榜 · 由账本机械生成</h2>",
        '<div class="note">' + esc(_note_pending()) + "</div>",
        f"<p>计分口径：{esc(SCORE_RULE)}</p>",
        f'<p class="muted">账本事件数：{len(list(events or ()))}'
        + (f" ｜ 统计截至：{esc(until)}" if until else "") + "</p>",
        table,
        "<h2>分数从哪来</h2>",
        "<p>本表由 <code>docs/bounty/ledger.json</code>（append-only 事件流）逐条累加 "
        "<code>delta</code> 算出——<b>不接受手写分数</b>；页面上任何分数都能在账本里"
        "找到对应事件。</p>",
        '<p class="muted">对外公开面＝本页 ＋ <code>docs/bounty/board.md</code>'
        "（同由账本生成）；内部镜像面不在本站内。</p>",
        "",
    ])
    return page("荣誉榜", "honor.html", body)


# 生效条件：无参数时返回规则页 HTML（认领-租约-验收四闸-声誉计分-争议）。
def render_rules() -> str:
    gates = "".join(f"<tr><td><b>{esc(n)}</b></td><td>{esc(d)}</td></tr>"
                    for n, d in ACCEPTANCE_GATES)
    rows = "".join(f"<tr><td><code>{esc(c)}</code></td><td>{esc(who)}</td>"
                   f"<td>{esc(chk)}</td><td>{esc(eff)}</td></tr>"
                   for c, who, chk, eff in COMMAND_ROWS)
    body = "\n".join([
        "<h2>一、状态机（六态）</h2>",
        "<pre>open ──/claim──▶ claimed ──/deliver──▶ delivered ──验收──▶ verified ──▶ settled\n"
        "                       │                                            │\n"
        "                       └── 72h 超时未交付 ──▶ 回板 open              "
        "└── 争议 ──▶ disputed</pre>",
        "<p><b>权威记录不是标签，而是评论里的机器标记</b>（<code>&lt;!-- bounty:v1 {…} --&gt;</code>）："
        "标签是人眼视图，标记是账。两者不一致时以标记为准。</p>",
        "<p><code>bounty:expired</code> 在 v0.1 <b>不驻留</b>：超时那一刻直接回板 "
        "<code>open</code>，只把「超时」事件与评论留在痕里。</p>",
        "<h2>二、认领与租约</h2>",
        "<p>认领即上锁，租约 <b>72 小时</b>；同一人并发认领上限 <b>2</b>；"
        "每 6 小时扫描一次，超期自动回板并记 −1。任何人可重新认领。</p>",
        "<h2>三、验收四闸（逐道可查 · 不通过就说不通过）</h2>",
        '<table><tr><th>闸</th><th>内容</th></tr>' + gates + "</table>",
        '<div class="note">第 ④ 闸是<b>维护者人审</b>——设计稿写死「维护者打 '
        "<code>bounty:verified</code>（含判定理由）」，<b>不许写成自动通过</b>。</div>",
        "<h2>四、命令面</h2>",
        '<table><tr><th>命令</th><th>谁用</th><th>校验</th><th>效果</th></tr>',
        rows, "</table>",
        "<h2>五、声誉计分</h2>",
        f"<p>{esc(SCORE_RULE)}</p>",
        '<div class="note">' + esc(_note_pending()) + "</div>",
        "<p>荣誉榜由账本机械生成（见 <a href=\"honor.html\">荣誉榜</a>）；"
        "账本 append-only、按事件 id 幂等去重。</p>",
        "<h2>六、争议</h2>",
        "<p>任一方 <code>/dispute &lt;理由&gt;</code> ⇒ 转 <code>bounty:disputed</code>；"
        "维护者在 issue 线程内给出仲裁（判定在前、读数对照在中、处置与边界在后）。"
        "<b>不扣本金，但记录在案。</b></p>",
        "",
    ])
    return page("规则", "rules.html", body)


# ================================================================ 生成入口


# 生效条件：ledger_path 为账本 JSON 路径、tasks 为可选快照列表、out_dir 为输出目录、print_only 为假时把四页写盘；返回落盘文件名列表（print_only 为真时不写盘）。
def build(ledger_path, out_dir, tasks=None, print_only=False) -> list:
    """从账本生成四页；返回落盘的文件名列表。"""
    events = bb.load_ledger(ledger_path)
    pages = (("index.html", render_index(events)),
             ("board.html", render_board(events, tasks)),
             ("honor.html", render_honor(events)),
             ("rules.html", render_rules()))
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
    return made


# 生效条件：path 为 tasks 快照 JSON 路径时返回任务列表（须为数组或 {"tasks":[...]}；结构不符抛 BoardError）。
def load_tasks(path):
    """读 issue 面快照（本地文件；本生成器不联网）。"""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise bb.BoardError(f"tasks 快照读取失败：{path}（{exc}）")
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and isinstance(doc.get("tasks"), list):
        return doc["tasks"]
    raise bb.BoardError(f"tasks 快照结构不符（须为数组或 {{'tasks': [...]}}）：{path}")


# 生效条件：argv 为命令行参数列表（None = sys.argv[1:]）时生成静态站并返回退出码——0 成功 / 2 输入或环境错误。
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="灵枢悬赏站 · 静态站生成器（纯 stdlib；从账本机械生成）")
    ap.add_argument("--ledger", default="docs/bounty/ledger.json",
                    help="账本 JSON（默认 docs/bounty/ledger.json）")
    ap.add_argument("--out", default="site", help="输出目录（默认 site/）")
    ap.add_argument("--tasks", default="",
                    help="issue 面快照 JSON（可选；不给则悬赏板从账本推演）")
    ap.add_argument("--print", dest="print_only", action="store_true",
                    help="只打印不落盘")
    args = ap.parse_args(argv)
    try:
        tasks = load_tasks(args.tasks)
        made = build(args.ledger, args.out, tasks=tasks,
                     print_only=args.print_only)
        events = bb.load_ledger(args.ledger)
        if args.print_only:
            print(f"（--print：{len(made)} 页未落盘；账本 "
                  f"{len(events)} 条事件）")
        else:
            print(f"站点已生成：{args.out}/（{', '.join(made)}；账本 "
                  f"{len(events)} 条事件）")
        return 0
    except bb.BoardError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
