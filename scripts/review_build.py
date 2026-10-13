# -*- coding: utf-8 -*-
"""灵枢悬赏站 · 插件测评子站生成器（纯 Python 标准库；**不触网、零第三方依赖**）。

真源：`review/data/plugins.json`   →   产物：`review/site/*.html`
用法：
    python -X utf8 scripts/review_build.py                 # 生成 review/site/
    python -X utf8 scripts/review_build.py --print          # 只打印不落盘
    python -X utf8 scripts/review_build.py --data X --out Y # 换真源 / 换输出目录
    python -X utf8 scripts/review_build.py --check          # 产物与真源一致则 0，漂移则 1

体例取自同仓既有三件（**先读**）：`scripts/build_site.py`（静态站生成器）、
`tests/test_build_site.py`（守卫 ＋ 定点变异）、`docs/bounty/README.md` §四。
本文件**不重造任何计分口径**——测评分（1/5 维，总分 ≤ 25）是本站自己的读数刻度，
与 `scripts/bounty_board.py` 的悬赏声誉分（1/3/6/10）**不是同一个量**，页面里必须写明，
避免两处口径被误读成同构。

★ **设计稿引用与边界注（如实声明，避免把读者引错产品）**
  悬赏清单 `eval-site` 条目的「参考材料」列了 `docs/spec/悬赏站设计_v1.0.md`。经核对，
  该文件实为《悬赏与项目管理平台 v1.0》——Django ＋ PostgreSQL ＋ Redis 的**独立平台**设计
  （里程碑／团队／完成码／赏金分配），且其 §7.0 明文写「本期不做 UI」、§1.3 写
  「**不接 GitHub / 读 PR / 托管代码**」。**它与本子站不是同一个产品**；本子站是
  `review/` 下的**限定增量**（静态产物、零依赖、不触网），不实现该设计稿的任何平台特性
  （无完成码、无赏金、无团队、无数据库）。故本文件**不引用该设计稿作为实现真源**，
  真正的体例真源是上列同仓三件。若维护者另有《插件测评子站设计》稿，请指出，届时改锚。

四页结构（中文界面）：
    index.html            首页——本子站是什么／怎么读表／引用纪律
    board.html            榜单——按总分降序（同分按插件名升序）
    detail_<slug>.html    测评详情——**每个插件一页**（维度表 ＋ 可复跑证据 ＋ 结论 ＋ 边界）
    method.html           方法说明——读数体例／评分刻度／未测项处理／复现步骤

一条硬口径（沿悬赏站设计）：**结算＝声誉制，不涉资金**——本站只放可核验读数，
页面里没有任何支付／钱包／链上概念，也没有任何资金字段可填。

★ **证据口径（本子站的诚实边界）**
  每条 `evidence` 必须写「命令 ＋ 原始输出」。输出若来自公开 README／文档的原文读数，
  必须在 `source` 里给出该文档 URL 与抓取日期，**不得**被读成「本站本机重跑过」。
  本机复跑得到的读数用 `source: "本机复跑"`。两种口径在页面上分列显示，不许混同。

确定性：**输出不含生成时刻**（同一真源 ⇒ 逐字节同一 HTML），便于守卫逐字节比对。

退出码：0 = 生成成功；1 = `--check` 检出产物漂移；2 = 输入／校验错误（fail-closed）。
"""
from __future__ import annotations

import argparse
import datetime
import html
import io
import json
import os
import re
import sys

#: 仓根——与 `scripts/bounty_list.py` 同口径（dirname(dirname(abspath(__file__)))），
#: 使喂给 `inspect.getsource` 的源码形态稳定，定点变异的锚点才可判。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 真源与产物默认位置（相对仓根）。
SRC = os.path.join(ROOT, "review", "data", "plugins.json")
OUT = os.path.join(ROOT, "review", "site")

#: 拒绝面错误串（单列成常量：定点变异可用它换词，而不必动 `MIN_PLUGINS` 判据本身）。
ERR_TOO_FEW = "插件数 %d < 下限 %d（验收标准要求 ≥%d 个插件记录）"

#: slug 白名单：只允许小写字母／数字／连字符，且以字母或数字开头（长度 2–64）。
#: slug 会被拼进 `detail_<slug>.html` 当**文档名**——不收口就能用 `../` 写到产物目录之外（路径穿越）。
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}[a-z0-9]")

#: 版本号形状（本子站只锚「字面声明的版本」，不替插件猜版本）。
VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")

#: URL 形状：必须是 http(s):// ＋ 非空主机名（只查 startswith("http") 会放行 "http"、"httpx"、"httpjunk"）。
URL_RE = re.compile(r"https?://[^\s/]+(?:/[^\s]*)?")

#: 页面里裸 URL 的匹配（linkify 用；**先转义再替换**，故不引入注入面）。
URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"'）)】]+")

#: 日期形状（`YYYY-MM-DD`；本子站不写时刻，避免产物随抓取时刻漂移）。
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

#: 五个测评维度（顺序即页面列序；**不是**五个「我觉得」——每条须有对应证据或标「未测」）。
DIMENSIONS = ("检索质量", "记忆持久", "注入预算", "隐私与本地性", "可验证性")

#: 单维度分域（整数）。总分 = 五维之和 ≤ 25。
DIM_MIN, DIM_MAX = 1, 5

#: 插件数下限（验收标准：`review/data/` 含 **≥3 个插件**记录）。
MIN_PLUGINS = 3

#: 证据来源档位（**本子站把「可复跑」从「转引」里显式切出去**的口径）。
#: `本机复跑` = 由 `scripts/evidence_probe.py` 的具名探针在本机跑出、且可被逐字节复算的 stdout；
#: `公开文档转引` = 引用公开 README／文档的原文读数（来源里必须给 URL 与抓取日）。
EVIDENCE_KINDS = ("本机复跑", "公开文档转引")

#: 每条记录至少要有几条 `本机复跑` 证据——验收标准要的是「命令 ＋ **原始输出**」，
#: 只判「output 是非空字符串」等于没有判据（任何手写文字都能过）。故设下限并强制。
MIN_LOCAL_EVIDENCE = 1

#: 引文最小长度：`'遗忘'`、`'99.2'` 这类短串在十万字节文档里几乎必然命中，属**无信息量引文**。
MIN_QUOTE_LEN = 6

#: **不可变引用**形状（版本面锚点）：tag 或 commit sha。
#: 为什么必须收口：`main` 会在**不升版本号**的情况下改文案——实测 `AskTheWay/dsh-auto-memory`
#: 的 `main` README 已从「78 tests／15 kB」改成「106 tests／~32 kB」而 version 仍是 0.7.1。
#: 锚在可变引用上的「版本面可核对」是不稳定的，故 `main`／`master`／`HEAD` 一律拒收。
IMMUTABLE_REF_RE = re.compile(r"/(?:v?\d+\.\d+\.\d+|[0-9a-f]{7,40})(?:/|$)")

#: 可变引用的具名黑名单（给出**点名**的拒绝理由，比只报「形状不符」可读）。
MUTABLE_REFS = ("/main/", "/master/", "/HEAD/")

#: ★ 口径标注：本站测评分与悬赏声誉分是两个量——页面凡出现分数处一并声明。
NOTE_PENDING = ("本子站的测评分（每维 1–5，总分 ≤ 25）是**本子站自己的读数刻度**，"
                "与 `scripts/bounty_board.py` 的悬赏声誉分（easy 1 ／ medium 3 ／ hard 6 ／ expert 10）"
                "**不是同一个量**，两者不可换算、不可相加。悬赏侧口径真源见 `docs/bounty/README.md` §四。")

#: 评分刻度说明（页面用；分数本身从真源求和，不手写）。
SCORE_RULE = ("每个维度按 **1–5 整数**打分（5 = 该维度上有可复跑证据且读数最好的一档；"
              "1 = 该维度上公开可得的信息最少或代价最高）；总分 = 五维之和（≤ 25）。"
              "打分**只依据本页列出的证据**——凡未取得读数的维度一律记 1 并在「未测」节说明原因，"
              "**不许**用「体验更好」「看起来更强」一类不可判表述代替读数。")

#: 未测项处理条款（页面用；验收标准要求显式写「未测 ＋ 原因」）。
UNMEASURED_RULE = ("**未测项**：凡本子站未取得原始输出的维度或子项，一律在详情页「未测」节"
                   "**显式写「未测 ＋ 原因」**——留空、或用「应该没问题」代替，视为未交付。"
                   "打分为 1 只表示「公开可得信息最少」，**不表示**该插件在该维度上差。")

#: 方法页「未测项怎么处理」小节标题（单列成常量：定点变异可用它换标记，从而证明该方法页确实在讲未测项）。
UNMEASURED_HEAD = "三、未测项怎么处理"

#: 零 LLM 判官条款（验收标准：禁用「看起来更好」「体验更佳」）。
NO_JUDGE_RULE = ("**零 LLM 判官**：本子站的每一条判定都能指回一条读数——"
                 "哪条读数支撑哪条结论逐项可指。禁用「看起来更好」「体验更佳」一类表述；"
                 "生成器本身也**不调用任何模型**、不发任何网络请求。")

#: 复现步骤（报告体例要求：环境、依赖、命令、预期耗时）。
REPRO_STEPS = (
    ("环境", "Python 3.12（与同仓其他脚本一致；`python -X utf8` 走 UTF-8）。"),
    ("依赖", "**零第三方依赖**——只用 Python 标准库（argparse／html／json／os／re／sys）。"),
    ("生成", "`python -X utf8 scripts/review_build.py`（写 `review/site/`）。"),
    ("守卫", "`python -X utf8 tests/test_review_build.py`（末行「通过 N / 失败 0」）。"),
    ("变异", "`python -X utf8 tests/test_review_build.py --mutate`（逐条恰好命中期望红项）。"),
    ("预期耗时", "生成 < 1 秒；守卫 < 5 秒；变异自证（逐条重跑守卫）< 60 秒。"),
    ("不触网", "以上命令**全程不发网络请求**；CI 里同样成立。"),
)


# ================================================================ 判据面（每条 = 一个可定点变异的函数）


# 生效条件：text 为任意值（含真源里来的不可信文本）时返回其 HTML 转义形态——真源内容一律先转义再进页面，防注入。
def esc(text) -> str:
    """HTML 转义（真源内容进页面前的唯一出口）。"""
    return html.escape(str(text), quote=True)


# 生效条件：text 为任意值时返回「先转义、再渲染行内 Markdown（粗体／行内代码）」的 HTML——**转义在前**，故不引入注入面。
def inline_md(text) -> str:
    """行内 Markdown 渲染（**粗体** → <b>，`代码` → <code>；先转义后替换，故不可注入）。"""
    out = esc(text)
    # 先替代码片段，避免「粗体标记落在代码里」被误渲染。
    out = re.sub(r"`([^`]+)`", lambda m: "<code>%s</code>" % m.group(1), out)
    out = re.sub(r"\*\*([^*]+)\*\*", lambda m: "<b>%s</b>" % m.group(1), out)
    return out


# 生效条件：text 为任意值时返回「先转义、再把裸 URL 变可点链接」的 HTML——**转义在前**，故 href 不可能被注入改写。
def linkify(text) -> str:
    """把裸 URL 渲染成可点链接（先 esc 再替换；href 里只可能是已转义的 URL 文本）。"""
    out = inline_md(text)

    def _a(m):
        u = m.group(0)
        return '<a href="%s" rel="noopener noreferrer" target="_blank">%s</a>' % (u, u)

    return URL_IN_TEXT_RE.sub(_a, out)


# 生效条件：d 为单个插件记录（dict）时返回错误串列表（空 = 该条合法）——逐条字段校验**只在本函数内**，故可被单独定点变异。
# 生效条件：text 为任意值时返回其是否为**真实存在的** `YYYY-MM-DD` 日期——形状与日历双判。
# 为什么不能只判形状：`2026-99-99` 也能过 `DATE_RE.fullmatch`，于是一个不存在的日期可以静默进页。
def date_ok(text) -> bool:
    """日期校验：形状 ＋ 日历（`datetime.date.fromisoformat`，零第三方依赖）。"""
    s = str(text or "")
    if not DATE_RE.fullmatch(s):
        return False
    try:
        datetime.date.fromisoformat(s)
    except ValueError:
        return False
    return True


def validate_record(d) -> list:
    """单条插件记录的字段校验；返回点名错误（空列表 = 合法）。"""
    errs = []
    slug = str(d.get("slug") or "")
    tag = slug or str(d.get("name") or "?")
    for key in ("name", "slug", "version", "source_url", "reviewed_at",
                "dimensions", "evidence", "conclusion", "boundary", "unmeasured"):
        if key not in d:
            errs.append("%s 缺字段 %s" % (tag, key))
    # 类型也要判：只判「键存在」会让 float/dict/list 混进文本字段，页面印出 Python repr。
    for key in ("name", "version", "source_url", "reviewed_at", "conclusion",
                "boundary", "unmeasured", "version_source", "version_checked_at"):
        if key in d and not isinstance(d[key], str):
            errs.append("%s %s 须为字符串（实得 %s）——否则页面会把 Python repr 当内容印出来"
                        % (tag, key, type(d[key]).__name__))
    if not str(d.get("name") or "").strip():
        errs.append("%s name 为空（验收标准要求每条含插件名）" % tag)
    if not VERSION_RE.search(str(d.get("version") or "")):
        errs.append("%s 版本无法锚定（须含形如 1.2.3 的字面版本）：%r"
                    % (tag, d.get("version")))
    if not URL_RE.fullmatch(str(d.get("source_url") or "")):
        errs.append("%s 来源 URL 非法（须 http(s)://＋主机名）：%r" % (tag, d.get("source_url")))
    # 版本面必须有权威来源——版本号不许从 README 的附带字符串里抄。
    vs = str(d.get("version_source") or "")
    if not URL_RE.fullmatch(vs):
        errs.append("%s 缺 version_source 或不是合法 URL（版本面权威面，如 package.json）：%r"
                    % (tag, d.get("version_source")))
    elif any(bad in vs for bad in MUTABLE_REFS):
        errs.append("%s version_source 锚在**可变引用**上（%s）——`main`/`master`/`HEAD` 会在"
                    "不升版本号的情况下改内容，实测已有一次（78 tests→106 tests 而 version 不变）。"
                    "请锚到不可变 tag 或 commit：%r"
                    % (tag, next(bad for bad in MUTABLE_REFS if bad in vs), vs))
    elif not IMMUTABLE_REF_RE.search(vs):
        errs.append("%s version_source 未锚到不可变引用（须含 tag 形如 `v1.2.3` 或 7–40 位 commit sha）：%r"
                    % (tag, vs))
    if not date_ok(d.get("version_checked_at")):
        errs.append("%s version_checked_at 须为**真实存在的** YYYY-MM-DD（形状＋日历双判）：%r"
                    % (tag, d.get("version_checked_at")))
    # 自评必须披露（利益相关）。
    if d.get("self_review") and not str(d.get("disclosure") or "").strip():
        errs.append("%s self_review=true 但缺 disclosure（自评必须显式披露利益相关）" % tag)
    if not date_ok(d.get("reviewed_at")):
        errs.append("%s reviewed_at 须为**真实存在的** YYYY-MM-DD（形状＋日历双判）：%r"
                    % (tag, d.get("reviewed_at")))
    dims = d.get("dimensions")
    if not isinstance(dims, dict) or set(dims) != set(DIMENSIONS):
        errs.append("%s dimensions 须恰为五维 %s：%r"
                    % (tag, "／".join(DIMENSIONS), dims))
    else:
        for k, v in dims.items():
            if not isinstance(v, int) or isinstance(v, bool) or not (DIM_MIN <= v <= DIM_MAX):
                errs.append("%s 维度 %s 越界（须 %d–%d 整数）：%r"
                            % (tag, k, DIM_MIN, DIM_MAX, v))
    # 未取得读数的维度必须记 1（无读数档）——否则「未测」就成了一个可以随便给中性分的挡箭牌。
    um = d.get("unmeasured_dims")
    if um is None:
        errs.append("%s 缺 unmeasured_dims（未取得读数的维度列表；没有就写 []）" % tag)
    elif not isinstance(um, list) or any(str(x) not in DIMENSIONS for x in um):
        errs.append("%s unmeasured_dims 须为维度名数组（可为空）：%r" % (tag, um))
    elif isinstance(dims, dict):
        bad_um = [x for x in um if dims.get(x) != 1]
        if bad_um:
            errs.append("%s 无读数维度必须记 1（当前 %s）——未测不等于可以给中性分"
                        % (tag, "，".join("%s=%r" % (x, dims.get(x)) for x in bad_um)))
    ev = d.get("evidence")
    if not isinstance(ev, list) or not ev:
        errs.append("%s evidence 为空（每条插件须 ≥1 条可复跑证据）" % tag)
    else:
        n_local = 0
        for i, e in enumerate(ev):
            if not isinstance(e, dict):
                errs.append("%s evidence[%d] 不是对象" % (tag, i))
                continue
            for k in ("cmd", "output", "source"):
                if not isinstance(e.get(k), str) or not e[k].strip():
                    errs.append("%s evidence[%d] %s 须为非空字符串（实得 %s）——"
                                "命令／原始输出／来源缺一不可"
                                % (tag, i, k, type(e.get(k)).__name__))
            # 来源档位：把「本机复跑」从「转引」里显式切出去。
            # 只判 output 非空是不够的——任何手写文字都能过，于是「可复跑证据」没有判据。
            kind = str(e.get("kind") or "")
            if kind not in EVIDENCE_KINDS:
                errs.append("%s evidence[%d] kind 须为 %s 之一（实得 %r）——"
                            "不标档位就无法区分「本机跑出来的」与「转引的」"
                            % (tag, i, "／".join(EVIDENCE_KINDS), e.get("kind")))
            elif kind == "本机复跑":
                n_local += 1
                if not str(e.get("probe") or "").strip():
                    errs.append("%s evidence[%d] 标了「本机复跑」却没写 probe（探针 id）——"
                                "没有具名探针就无法逐字节复算这段输出" % (tag, i))
            elif str(e.get("probe") or "").strip():
                errs.append("%s evidence[%d] 是「公开文档转引」却写了 probe=%r——"
                            "转引不是本机跑出来的，不许挂探针"
                            % (tag, i, e.get("probe")))
            # 证据链：出处快照 + 逐字引文（由 scripts/evidence_check.py 离线复核）
            if not str(e.get("doc") or "").strip():
                errs.append("%s evidence[%d] 缺 doc（引文出自哪个快照）" % (tag, i))
            qs = e.get("quotes")
            if not isinstance(qs, list) or not qs or not all(
                    str(q).strip() for q in qs):
                errs.append("%s evidence[%d] quotes 须为非空字符串数组（逐字引文）" % (tag, i))
            else:
                weak = [q for q in qs if len(str(q).strip()) < MIN_QUOTE_LEN]
                if weak:
                    errs.append("%s evidence[%d] 有 %d 条引文短于 %d 字符（%s）——"
                                "短串在长文档里几乎必然命中，属无信息量引文，请换成整句"
                                % (tag, i, len(weak), MIN_QUOTE_LEN,
                                   "，".join(repr(w) for w in weak[:3])))
        if n_local < MIN_LOCAL_EVIDENCE:
            errs.append("%s 只有 %d 条「本机复跑」证据，少于下限 %d——"
                        "验收标准要的是「命令 ＋ **原始输出**」；全部靠转引不算可复跑证据"
                        % (tag, n_local, MIN_LOCAL_EVIDENCE))
    for k in ("conclusion", "boundary", "unmeasured"):
        if not str(d.get(k) or "").strip():
            errs.append("%s %s 为空（结论／边界／未测项均须显式写）" % (tag, k))
    if not str(slug).strip():
        errs.append("%s slug 为空（slug 是详情页文件名，不许空）" % tag)
    elif not slug_ok(slug):
        errs.append("%s slug 非法（只许小写字母／数字／连字符、长度 2–64）：%r —— "
                    "白名单本身即排除路径分隔符与回退段，故 slug 不可能写到产物目录之外"
                    % (tag, slug))
    return errs


# 生效条件：slug 为待用作文档名的串时返回其是否合法（只允许小写字母／数字／连字符，长度 2–64）。
def slug_ok(slug) -> bool:
    """slug 必须是安全文档名。

    这一条**同时**承担两件事，故不需要再单列一道「路径闸」：
      ① 防路径穿越——白名单里没有 `/`、`\\`、`:`、`.`，故 `../`、盘符、绝对路径都拼不出来；
      ② 防怪名——大写、下划线、空格、超长一律拒收。
    （早期版本另有一道 `slug_path_safe` 纵深防御，实测被本白名单**完全遮蔽**：
    对 `../../evil` 之类输入，白名单先一步拒收，那道闸的行为无从观测、也无法用变异证明。
    故删掉重复判据，只留这一条可被定点变异证伪的收口。）
    """
    return bool(SLUG_RE.fullmatch(str(slug)))


# 生效条件：doc 为真源文档（dict）时返回错误串列表（空 = 全仓合法）——管「条数下限」与「slug 唯一」两条全局判据。
def validate(doc) -> list:
    """真源全量校验；返回点名错误（空列表 = 合法）。"""
    errs = []
    recs = doc.get("records") if isinstance(doc, dict) else None
    if not isinstance(recs, list):
        return ["records 缺失或不是数组"]
    seen = set()
    for d in recs:
        if not isinstance(d, dict):
            errs.append("记录不是对象：%r" % (d,))
            continue
        errs.extend(validate_record(d))
        slug = str(d.get("slug") or "")
        if slug in seen:
            errs.append("slug 重复：%s（slug 是详情页文件名，必须唯一）" % slug)
        seen.add(slug)
    if len(recs) < MIN_PLUGINS:
        errs.append(ERR_TOO_FEW % (len(recs), MIN_PLUGINS, MIN_PLUGINS))
    return errs


# 生效条件：path 为真源 JSON 路径时返回文档（dict）；读取或解析失败抛 ValueError（由 main 收成 fail-closed）。
def load_data(path):
    """读真源（本地文件；本生成器不联网）。"""
    try:
        with io.open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError("真源读取失败：%s（%s）" % (path, exc))
    if not isinstance(doc, dict):
        raise ValueError("真源结构不符（须为对象，含 records 数组）：%s" % path)
    return doc


# 生效条件：d 为已校验的插件记录时返回其总分（五维求和，**从真源算、不接受手写总分字段**）。
def total_score(d) -> int:
    """总分 = 五维之和（≤ 25）。"""
    return sum(int(v) for v in d["dimensions"].values())


# 生效条件：n 为某条记录的算得总分时返回榜面显示串——榜面分值的**唯一**出口，便于单独钉住「榜面分数＝算得分数」。
def format_total(n) -> str:
    """榜面分值显示串（承载体：`<b>…</b>`）。"""
    return "<b>%d</b>" % int(n)


# 生效条件：d 为已校验的插件记录时返回 (本机复跑条数, 公开文档转引条数)——榜面「证据」列的唯一出口。
def kind_counts(d) -> tuple:
    """记录 → (本机复跑, 公开文档转引) 条数。"""
    ev = [e for e in (d.get("evidence") or []) if isinstance(e, dict)]
    n_local = sum(1 for e in ev if e.get("kind") == "本机复跑")
    return n_local, len(ev) - n_local


# 生效条件：recs 为插件记录列表时返回榜单行列表，按「总分降序、插件名升序」排——榜单次序的唯一判据。
def leaderboard(recs) -> list:
    """真源 → 榜单行（含算出的总分）。"""
    rows = []
    for d in recs:
        rows.append({"name": str(d["name"]), "slug": str(d["slug"]),
                     "version": str(d["version"]),
                     "source_url": str(d["source_url"]),
                     "total": total_score(d), "record": d})
    return sorted(rows, key=_rank_key)


# 生效条件：row 为榜单行时返回排序键（总分降序、插件名升序）——名次次序的唯一判据。
def _rank_key(row):
    return (-row["total"], row["name"])


# 生效条件：recs 为插件记录列表时返回「slug → 记录」映射（详情页取数用；校验已保证 slug 唯一）。
def by_slug(recs) -> dict:
    return {str(d["slug"]): d for d in recs}


# ================================================================ HTML 外壳与四页


# 生效条件：title/active/body 给定时返回整页 HTML（内联 CSS、无外部资源、UTF-8）；active 为当前页文件名（导航高亮）。
def page(title, active, body) -> str:
    nav = (("index.html", "首页"), ("board.html", "榜单"),
           ("method.html", "方法说明"))
    links = "".join(
        '<a class="%s" href="%s">%s</a>' % ("on" if fn == active else "", fn, name)
        for fn, name in nav)
    return "\n".join([
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>%s · 灵枢插件测评</title>" % esc(title),
        "<style>",
        CSS,
        "</style>",
        "</head>",
        "<body>",
        '<header><h1><a href="index.html">灵枢插件测评</a></h1>',
        "<nav>%s</nav></header>" % links,
        "<main>",
        body,
        "</main>",
        '<footer>本页由 <code>scripts/review_build.py</code> 从 '
        '<code>review/data/plugins.json</code> 机械生成——勿手改。'
        '本站只放可核验读数，<b>不涉资金</b>，<b>不采集用户隐私</b>。</footer>',
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
pre{background:var(--soft);padding:12px;border-radius:5px;overflow:auto;font-size:13px}
.note{background:#fff8e1;border-left:4px solid #f0ad4e;padding:10px 14px;margin:14px 0}
.muted{color:var(--dim)}
.tag{display:inline-block;background:var(--soft);border:1px solid var(--line);
 border-radius:10px;padding:0 8px;font-size:12px;margin-right:6px}
footer{border-top:1px solid var(--line);margin-top:36px;padding:16px 24px;
 color:var(--dim);font-size:13px}
"""


# 生效条件：recs 为插件记录列表时返回「未测项」区块 HTML（每条记录一行：插件名 ＋ 未测项文本）；真源无记录时给空串。
def render_unmeasured(recs) -> str:
    """「未测 ＋ 原因」区块——验收标准要求显式写，故独立成块、可被定点变异。"""
    if not recs:
        return ""
    rows = "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (esc(d["name"]), inline_md(d["unmeasured"]))
        for d in recs)
    return "\n".join([
        "<h2>未测项（显式写「未测 ＋ 原因」）</h2>",
        '<div class="note">%s</div>' % inline_md(UNMEASURED_RULE),
        "<table><tr><th>插件</th><th>未测项 ＋ 原因</th></tr>%s</table>" % rows,
        "",
    ])


# 生效条件：recs 为插件记录列表时返回首页 HTML（这是什么／怎么读表／引用纪律／下一步）。
def render_index(recs) -> str:
    rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (esc(k), inline_md(v))
                   for k, v in REPRO_STEPS)
    body = "\n".join([
        "<h2>这是什么</h2>",
        "<p>灵枢悬赏站的<b>插件测评子站</b>：把「某个插件到底行不行」拆成"
        "<b>可复跑的读数</b>——每条测评都给命令与原始输出，判定逐项可指回读数。</p>",
        '<div class="note"><b>不涉资金</b>：本子站只放可核验读数，不做排名激励、'
        "不涉任何支付／钱包／链上概念。%s</div>" % inline_md(NOTE_PENDING),
        "<h2>怎么读表</h2>",
        "<ol>",
        "<li>先看 <a href=\"board.html\">榜单</a>：总分 = 五个维度各自 1–5 分求和（≤ 25）。</li>",
        "<li>再点进<b>测评详情</b>：维度表 ＋ 每条证据的<b>命令与原始输出</b> ＋ 结论 ＋ 边界。</li>",
        "<li>凡未取得读数的项，在「未测」节<b>显式写「未测 ＋ 原因」</b>——不要把它读成 0 分。</li>",
        "<li>想看口径怎么定的，去 <a href=\"method.html\">方法说明</a>。</li>",
        "</ol>",
        "<h2>引用纪律</h2>",
        "<ul>",
        "<li>每条证据必须写清 <b>命令 ＋ 原始输出 ＋ 来源</b>：三项缺一，生成器直接 fail-closed 拒绝出站。</li>",
        "<li>证据**分两档**，逐条在详情页顶部标出：<code>本机复跑</code>（由具名探针跑出，"
        "输出被 <code>evidence_check.py --repro</code> 逐字节复算）与 <code>公开文档转引</code>"
        "（取自公开文档原文读数，来源里给出 URL 与抓取日期——<b>不得</b>被读成本站本机重跑）。</li>",
        "<li>**每条记录至少 1 条「本机复跑」**——只靠转引不算「命令 ＋ 原始输出」。这条由生成器强制。</li>",
        "</ul>",
        "<h2>复现步骤</h2>",
        "<table><tr><th>项</th><th>内容</th></tr>%s</table>" % rows,
        "<h2>下一步</h2>",
        '<p><a href="board.html">去榜单看总分排序</a> ｜ '
        '<a href="method.html">读方法说明与评分刻度</a></p>',
        "",
    ])
    return page("首页", "index.html", body)


# 生效条件：recs 为插件记录列表时返回榜单 HTML（行数 = 插件数；按总分降序、同分按插件名升序；总分由五维求和算出）。
def render_board(recs) -> str:
    rows = leaderboard(recs)
    if rows:
        trs = []
        for i, r in enumerate(rows, 1):
            d = r["record"]
            detail = "detail_%s.html" % esc(r["slug"])
            nature = "自评" if d.get("self_review") else "他评"
            n_local, n_quote = kind_counts(d)
            trs.append("<tr><td>%d</td><td><a href=\"%s\">%s</a></td>"
                       "<td>%s</td><td>%s</td><td>%s</td><td>%d / %d</td><td>%s</td></tr>"
                       % (i, detail, esc(r["name"]), esc(r["version"]),
                          format_total(r["total"]), nature, n_local, n_quote,
                          linkify(r["source_url"])))
        table = ("<table><tr><th>#</th><th>插件</th><th>版本</th><th>总分</th>"
                 "<th>性质</th><th>证据（本机复跑 / 转引）</th><th>来源</th></tr>"
                 + "".join(trs) + "</table>")
    else:
        table = '<p class="muted">（真源里没有插件记录——补齐 review/data/plugins.json 后本表自动出现。）</p>'
    self_n = sum(1 for r in rows if r["record"].get("self_review"))
    body = "\n".join([
        "<h2>榜单 · 总分降序</h2>",
        '<div class="note">%s</div>' % inline_md(NOTE_PENDING),
        ("<p><b>性质列</b>：「自评」＝被评插件与本站维护者同源（当前 %d 条），"
         "其分值不应与他评条目等权看待；每条自评的详情页顶部都有利益相关声明。</p>" % self_n),
        "<p>计分口径：%s</p>" % inline_md(SCORE_RULE),
        table,
        "<h2>怎么看这个榜</h2>",
        "<p>总分只是<b>五维读数之和</b>，不是「谁更好」的总判决——"
        "不同插件面向的用法不同，请点进详情页对着<b>证据命令</b>自己判。</p>",
        "<p>同分时按插件名升序排（次序稳定、可复现）。</p>",
        "",
    ])
    return page("榜单", "board.html", body)


# 生效条件：d 为单条插件记录时返回该插件的测评详情页 HTML（含 slug 锚点／维度表／证据命令＋原始输出／结论／边界／未测）。
def render_detail(d) -> str:
    dim_rows = "".join(
        "<tr><td>%s</td><td><b>%d</b></td></tr>" % (esc(k), int(d["dimensions"][k]))
        for k in DIMENSIONS)
    ev_blocks = []
    for i, e in enumerate(d["evidence"], 1):
        kind = str(e.get("kind") or "（未标档位）")
        ev_blocks.append("<h3>证据 %d <span class=\"tag\">%s</span></h3>"
                         % (i, esc(kind)))
        if kind == "本机复跑":
            # 本机复跑的证据必须能被逐字节复算：把探针 id 与复算命令一并印出来。
            ev_blocks.append("<p class=\"muted\">本机复跑（探针 <code>%s</code>）——"
                             "复算：<code>python -X utf8 scripts/evidence_probe.py %s</code>；"
                             "`python -X utf8 scripts/evidence_check.py --repro` 会逐字节比对。</p>"
                             % (esc(e.get("probe") or "?"), esc(e.get("probe") or "?")))
        else:
            ev_blocks.append("<p class=\"muted\">公开文档转引——引自下列快照，"
                             "<b>不是</b>本站本机跑出来的读数。</p>")
        ev_blocks.append("<p><b>① 复跑命令</b></p>")
        ev_blocks.append("<pre>%s</pre>" % esc(e["cmd"]))
        ev_blocks.append("<p><b>② 原始输出</b>（%s）</p>" % linkify(e["source"]))
        ev_blocks.append("<pre>%s</pre>" % esc(e["output"]))
        # 证据链：出处快照 + 逐字引文——引文可离线复核（scripts/evidence_check.py）
        ev_blocks.append("<p><b>③ 出处快照</b>：<code>review/evidence/%s</code></p>"
                         % esc(e.get("doc") or "（未声明）"))
        qs = e.get("quotes") or []
        if qs:
            items = "".join("<li><code>%s</code></li>" % esc(q) for q in qs)
            ev_blocks.append("<p><b>④ 逐字引文</b>（在快照里按字节子串核对）：</p>")
            ev_blocks.append("<ul>%s</ul>" % items)
    body = "\n".join([
        '<a id="%s"></a>' % esc(d["slug"]),
        "<h2>%s · 测评详情</h2>" % esc(d["name"]),
        "<p><span class=\"tag\">版本 %s</span>"
        "<span class=\"tag\">测评日 %s</span>"
        "<span class=\"tag\">总分 %d / %d</span>"
        "<span class=\"tag\">%s</span></p>"
        % (esc(d["version"]), esc(d["reviewed_at"]), total_score(d),
           DIM_MAX * len(DIMENSIONS),
           "自评（作者同源）" if d.get("self_review") else "他评"),
        # 自评必须把利益相关摆在最前面，读者不该翻到底才发现。
        ("<div class=\"note\">%s</div>" % inline_md(d["disclosure"])
         if str(d.get("disclosure") or "").strip() else ""),
        "<p>来源：%s</p>" % linkify(d["source_url"]),
        "<p>版本面：%s（核对日 %s）</p>"
        % (linkify(d.get("version_source") or "（未声明）"),
           esc(d.get("version_checked_at") or "—")),
        "<h2>维度读数</h2>",
        "<table><tr><th>维度</th><th>分（1–%d）</th></tr>%s</table>"
        % (DIM_MAX, dim_rows),
        ("<p class=\"muted\">无读数维度（记 1）：%s</p>"
         % "、".join(esc(x) for x in (d.get("unmeasured_dims") or []))
         if d.get("unmeasured_dims") else ""),
        "<h2>可复跑证据（命令 ＋ 原始输出）</h2>",
        "\n".join(ev_blocks),
        "<h2>结论</h2>",
        "<p>%s</p>" % inline_md(d["conclusion"]),
        "<h2>边界 · 不适用条件</h2>",
        "<p>%s</p>" % inline_md(d["boundary"]),
        "<h2>未测项（未测 ＋ 原因）</h2>",
        "<p>%s</p>" % inline_md(d["unmeasured"]),
        "<p><a href=\"board.html\">← 回榜单</a></p>",
        "",
    ])
    return page("%s 测评详情" % d["name"], "board.html", body)


# 生效条件：recs 为插件记录列表时返回方法说明页 HTML（读数体例／评分刻度／未测项处理／零 LLM 判官／复现步骤）。
def render_method(recs) -> str:
    dim_rows = "".join("<tr><td>%s</td><td>%d–%d</td></tr>" % (esc(k), DIM_MIN, DIM_MAX)
                       for k in DIMENSIONS)
    step_rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (esc(k), inline_md(v))
                        for k, v in REPRO_STEPS)
    body = "\n".join([
        "<h2>〇、口径先说清</h2>",
        '<div class="note">%s</div>' % inline_md(NOTE_PENDING),
        "<h2>一、怎么读一条测评</h2>",
        "<p>一条测评 = ①维度读数 ②每条证据的<b>命令 ＋ 原始输出 ＋ 来源</b> ③结论 ④边界"
        " ⑤未测项。缺任何一项，生成器在落盘前就拒绝（fail-closed）；"
        "落盘期失败（磁盘／权限）同样点名并以退出码 2 收场，不留半截站。</p>",
        "<p>%s</p>" % inline_md(NO_JUDGE_RULE),
        "<h2>二、评分刻度</h2>",
        "<p>%s</p>" % inline_md(SCORE_RULE),
        "<table><tr><th>维度</th><th>分域</th></tr>%s</table>" % dim_rows,
        "<h2>%s</h2>" % esc(UNMEASURED_HEAD),
        "<div class=\"note\">%s</div>" % inline_md(UNMEASURED_RULE),
        "<h2>四、证据来源的两档（**本子站把「可复跑」从「转引」里切出去**）</h2>",
        "<table><tr><th>来源档</th><th>字段</th><th>含义与判据</th></tr>"
        "<tr><td><code>本机复跑</code></td><td><code>kind</code> ＋ <code>probe</code></td>"
        "<td>由 <code>scripts/evidence_probe.py</code> 的具名探针在本机跑出；"
        "<code>output</code> 必须与该探针的 stdout <b>逐字节相同</b>——"
        "由 <code>python -X utf8 scripts/evidence_check.py --repro</code> 每次复算，"
        "差一个字节即点名判红。<b>每条记录至少 1 条</b>（生成器强制）。</td></tr>"
        "<tr><td><code>公开文档转引</code></td><td><code>source</code>（URL ＋ 抓取日）</td>"
        "<td>原始输出取自该公开文档的原文读数（<b>不是</b>本站本机重跑）；"
        "URL 与抓取日期随证据一并公开，可自行核验。<b>不得</b>挂 <code>probe</code>。</td></tr>"
        "</table>",
        "<div class=\"note\"><b>本机复跑证明了什么、没证明什么</b>：它证明"
        "「我们引的字节就是这些字节」「这条命令现在仍然跑得出这段输出」；"
        "它<b>不</b>证明被测评插件的运行时行为。凡未取得原始输出的维度，"
        "一律记 1（无读数档）并在「未测」节写明原因。</div>",
        "<h2>五、复现步骤</h2>",
        "<table><tr><th>项</th><th>内容</th></tr>%s</table>" % step_rows,
        "",
    ])
    return page("方法说明", "method.html", body)


# ================================================================ 生成入口


# 生效条件：recs 为已校验的插件记录列表时返回「(文件名, 整页文本)」列表——**页面集合的唯一来源**，落盘与 --check 共用它，防两处漂移。
def render_pages(recs) -> list:
    """真源记录 → 全部页面（文件名 ＋ 文本），次序稳定。"""
    pages = [("index.html", render_index(recs)),
             ("board.html", render_board(recs)),
             ("method.html", render_method(recs))]
    for d in recs:
        pages.append(("detail_%s.html" % d["slug"], render_detail(d)))
    return pages


# 生效条件：doc 为已校验的真源文档、out_dir 为输出目录、print_only 为假时把各页写盘；返回落盘文件名列表（print_only 为真时不写盘）。
def build(doc, out_dir, print_only=False) -> list:
    """从真源生成各页；返回落盘的文件名列表。"""
    pages = render_pages(doc["records"])
    if print_only:
        for name, text in pages:
            sys.stdout.write("===== %s =====\n%s" % (name, text))
        return [name for name, _ in pages]
    os.makedirs(out_dir, exist_ok=True)
    keep = {name for name, _ in pages}
    made = []
    try:
        for name, text in pages:
            with io.open(os.path.join(out_dir, name), "w", encoding="utf-8",
                         newline="\n") as fh:
                fh.write(text)
            made.append(name)
    except OSError as exc:
        # 落盘期失败（磁盘满／权限）也要走 fail-closed，且**点名**——
        # 早先版本让它抛栈回溯，退出码既不是 2 也没有说清是哪一页。
        raise ValueError("产物落盘失败（已写 %d/%d 页）：%s（%s）"
                         % (len(made), len(pages), out_dir, exc))
    # 清掉**上次生成、这次不该有**的页面：否则真源删掉一个插件后，旧的 detail_<slug>.html
    # 会留在产物目录里，`--check` 也发现不了（它只比对自己渲染的那些页）——产物就与真源不一致了。
    removed = stale_pages(out_dir, keep)
    if removed:
        print("已清理上次遗留的页面：%s" % "，".join(removed))
    # 只报不删：`--out` 里**不属于本子站**的东西（例如误指向 build_site.py 的 `site/`）。
    foreign = foreign_pages(out_dir, keep)
    if foreign:
        print("注意：产物目录里还有 %d 个不属于本子站的文件（未删）：%s"
              % (len(foreign), "，".join(foreign)))
    return made


# 生效条件：out_dir 为产物目录、keep 为本次应存在的文件名集合时，删除目录内**不在 keep 里**的
# `detail_*.html` 页，返回被删名单（排序）——只删**本子站会生成的那种具名形态**。
# 为什么收窄到 `detail_`：`--out` 是用户给的参数，同仓 `scripts/build_site.py` 的默认输出目录
# 恰好也叫 `site`，两站固定页名还重叠（都有 index.html／board.html）。无差别删 `*.html` 会让
# `review_build.py --out site` 一声不响地删掉 `site/honor.html`、`site/rules.html`。
# index／board／method 三个固定页恒在 keep 里，故收窄不影响「旧 slug 页要被清掉」这条语义。
def stale_pages(out_dir, keep) -> list:
    """清理产物目录里上次遗留的 `detail_*.html` 页（产物目录应当是专用的）。"""
    removed = []
    if not os.path.isdir(out_dir):
        return removed
    for name in sorted(os.listdir(out_dir)):
        if not name.startswith("detail_") or not name.endswith(".html") or name in keep:
            continue
        p = os.path.join(out_dir, name)
        if os.path.isfile(p):
            os.remove(p)
            removed.append(name)
    return removed


# 生效条件：out_dir 为产物目录、keep 为本次应存在的文件名集合时返回**不属于本次产物的**文件名单（排序）。
# 存在的理由：`--out` 指向别的生成器的目录（例如 `site/`）时，本子站**只报不删**，
# 让使用者自己看见「这里混进了别的东西」，而不是被静默清掉。
def foreign_pages(out_dir, keep) -> list:
    """产物目录里不属于本子站的文件（只报不删——防误删别人的产物）。"""
    if not os.path.isdir(out_dir):
        return []
    return sorted(n for n in os.listdir(out_dir)
                  if n not in keep and os.path.isfile(os.path.join(out_dir, n)))


# 生效条件：out_dir 为产物目录、names 为本次应存在的文件名集合时返回该目录里**多出来的**文件
# （排序；不限扩展名）——`--check` 的漏报面。为什么不限 `.html`：只比 `.html` 会漏掉
# 「产物目录里混进了一个非 .html 的残留文件」，而「产物与真源一致」这句话是全覆盖的。
def extra_pages(out_dir, names) -> list:
    """产物目录里不在应存在集合内的文件（--check 必须能发现它们，否则「一致」是假的安全感）。"""
    if not os.path.isdir(out_dir):
        return []
    return sorted(n for n in os.listdir(out_dir)
                  if n not in names and os.path.isfile(os.path.join(out_dir, n)))


# 生效条件：argv 为命令行参数列表（None = sys.argv[1:]）时生成子站并返回退出码——0 成功 / 1 漂移 / 2 输入或校验错误。
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="灵枢插件测评子站生成器（纯 stdlib；从真源机械生成）")
    ap.add_argument("--data", default=SRC, help="真源 JSON（默认 review/data/plugins.json）")
    ap.add_argument("--out", default=OUT, help="输出目录（默认 review/site）")
    ap.add_argument("--print", dest="print_only", action="store_true",
                    help="只打印不落盘")
    ap.add_argument("--check", dest="check_only", action="store_true",
                    help="只校验产物与真源一致（漂移则退出码 1）")
    args = ap.parse_args(argv)
    # 互斥标志：`--check` 只校验、`--print` 只打印，同时给等于没说清意图。
    # 同仓 `scripts/bounty_list.py` 同样先判 `--stdout` 再判 `--check`；此处**显式拒收**，
    # 免去「谁优先」的隐式口径（早先版本是 `--check` 静默压过 `--print`）。
    if args.check_only and args.print_only:
        sys.stderr.write("[错误] `--check` 与 `--print` 互斥：前者只校验产物，后者只打印不落盘；"
                         "请二选一。\n")
        return 2
    try:
        doc = load_data(args.data)
    except ValueError as exc:
        sys.stderr.write("[错误] %s\n" % exc)
        return 2
    errs = validate(doc)
    if errs:
        sys.stderr.write("真源校验失败（fail-closed，未写任何产物）：\n")
        for e in errs:
            sys.stderr.write("  - %s\n" % e)
        return 2

    recs = doc["records"]
    if args.check_only:
        pages = render_pages(recs)
        names = {name for name, _ in pages}
        drift = []
        for name, text in pages:
            p = os.path.join(args.out, name)
            # **字节级**比对：文本模式读盘会把 CRLF／CR 归一成 LF，
            # 于是「产物只差行尾」这种真实漂移判不出来。
            cur = None
            try:
                with open(p, "rb") as fh:
                    cur = fh.read()
            except OSError:
                cur = None
            if cur != text.encode("utf-8"):
                drift.append(name)
        # 多出来的文件也算漂移——只比对自己渲染的页会漏报「上次遗留的旧 slug 页」。
        extra = extra_pages(args.out, names)
        if drift or extra:
            if drift:
                sys.stderr.write("产物与真源漂移：%s\n" % "，".join(drift))
            if extra:
                sys.stderr.write("产物目录里多出不该有的文件（真源里已无此插件／非本子站产物）：%s\n"
                                 % "，".join(extra))
            return 1
        print("产物与真源一致：%s（%d 页，%d 个插件）"
              % (args.out, len(pages), len(recs)))
        return 0

    try:
        made = build(doc, args.out, print_only=args.print_only)
    except ValueError as exc:
        sys.stderr.write("真源校验通过，但生成失败（fail-closed）：%s\n" % exc)
        return 2
    if args.print_only:
        print("（--print：%d 页未落盘；%d 个插件）" % (len(made), len(recs)))
    else:
        print("子站已生成：%s/（%s；%d 个插件）"
              % (args.out, "，".join(made), len(recs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
