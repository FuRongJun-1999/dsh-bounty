# -*- coding: utf-8 -*-
"""灵枢悬赏站 · 插件测评子站生成器（纯 Python 标准库；**不触网、零第三方依赖**）。

真源：`review/data/plugins.json`（读数）＋ `review/data/rubric.json`（判据）
   →   产物：`review/site/*.html`
用法：
    python -X utf8 scripts/review_build.py                 # 生成 review/site/
    python -X utf8 scripts/review_build.py --print          # 只打印不落盘
    python -X utf8 scripts/review_build.py --data X --out Y # 换真源 / 换输出目录
    python -X utf8 scripts/review_build.py --check          # 产物与真源一致则 0，漂移则 1
    python -X utf8 scripts/review_build.py --rubric-report  # 逐维复核：分 ↔ 档位 ↔ 证据下标 ↔ must ↔ rationale

体例取自同仓既有三件（**先读**）：`scripts/build_site.py`（静态站生成器）、
`tests/test_build_site.py`（守卫 ＋ 定点变异）、`docs/bounty/README.md` §四。
本文件**不重造任何计分口径**——测评分（每维 1–5，榜面报**已测维度均值**）是本站自己的读数刻度，
与 `scripts/bounty_board.py` 的悬赏声誉分（1/3/6/10）**不是同一个量**，页面里必须写明，
避免两处口径被误读成同构。

★ **两个正交的轴（v2 口径；v1 的缺陷已确认）**
  ① **表现水平**：`dimensions[维度]` = 1–5 整数，`null` = 该维**无任何证据**（`dim_basis` 为空，无法判级）。
     判据真源是 `review/data/rubric.json` 的 `levels[维度][分数]`（`meaning` 人读／`must` 机判）。
  ② **证据档位**：由 `dim_basis[维度]` 指向的证据**机械推导**（none／prose／reading／repro），
     只在榜面**披露**，**不参与**排序与求和。
  v1 把两轴合成一个「五维求和」的总分，有两个已确认缺陷：
  (a) 「无任何证据」伪装成 `1` 参与求和 ⇒ 覆盖率低的记录被**系统性低估**；
  (b) 合一了「表现水平」与「证据强度」两个正交的轴。
  故 v2：未测维度记 `null` 且**不参与**任何合计；档位与覆盖率**分列**披露——
  **不降权**是因为降权要新造一个系数，那属于**新造读数**。

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
    board.html            榜单——按**已测维度均值**降序（三段分列：他评榜／证据不足／自评）
    detail_<slug>.html    测评详情——**每个插件一页**（维度表：分＋档位＋rationale ＋ 可复跑证据 ＋ 结论 ＋ 边界）
    method.html           方法说明——五维各量什么／两轴口径／未测项处理／证据档位／复现步骤

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

#: **判据真源**：五维的**表现水平**判据（`levels[维度][分数].meaning／must`）与**证据档位**枚举。
#: 「几分算几级、拿到该级要什么证据」只由它说了算——生成器不重造判据、不手写分数。
RUBRIC_PATH = os.path.join(ROOT, "review", "data", "rubric.json")

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

#: **证据档位**（第二条轴）：由 `dim_basis` 指向的证据机械推导，只披露、不参与求和。
#: none = 无证据；prose = 有证据但无数字读数；reading = 有可核数字读数；repro = 有本机复跑证据。
TIERS = ("none", "prose", "reading", "repro")

#: 单维度分域（整数）。`null` 表示该维**无任何证据**（`dim_basis` 为空，不进任何合计）。
DIM_MIN, DIM_MAX = 1, 5

#: 插件数下限（验收标准：`review/data/` 含 **≥3 个插件**记录）。
MIN_PLUGINS = 3

#: **他评榜**的覆盖率门槛：已测维度 ≥ 3/5 才排名，不足者单列「证据不足，暂不排名」。
#: 为什么是 3：少于 3 维的均值由一两个读数决定，与满覆盖的记录并排会诱导误读。
MIN_RANKED_COVERAGE = 3

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
NOTE_PENDING = ("本子站的测评分（每维 1–5 整数，**`dim_basis` 为空（无任何证据）的维度记 `null`**；榜面报的是"
                "**已测维度均值**，不再是五维求和）是**本子站自己的读数刻度**，"
                "与 `scripts/bounty_board.py` 的悬赏声誉分（easy 1 ／ medium 3 ／ hard 6 ／ expert 10）"
                "**不是同一个量**，两者不可换算、不可相加。悬赏侧口径真源见 `docs/bounty/README.md` §四。")

#: 评分刻度说明（页面用；分数本身从真源读、判级依据从 rubric 读，都不手写）。
SCORE_RULE = ("每个维度按 **1–5 整数**打分，判级依据是**判据真源** `review/data/rubric.json` 的"
              "`levels[维度][分数]`（5 = 该维度上有可复跑证据且读数最好的一档）。"
              "**`dim_basis` 为空的维度记 `null`**（**无任何证据**）——它不进均值、也不作为 1 计入分母；"
              "`1..5` 都表示**有基座**（该维挂了 ≥1 条证据）：`1` 是最低档、`5` 是最高档，"
              "**1–4 级的机械门槛都只是「基座非空」**。"
              "榜面报的是**已测维度均值**（保留 2 位）与**覆盖率**（已测维度数 ／ 5），"
              "**不再是**五维求和。打分**只依据页面上列出的证据**——"
              "禁用「体验更好」「看起来更强」一类不可判表述。")

#: 二轴口径里最容易误读的一条：凡出现分数处一并印出（`null` ≠ 最低档）。
NULL_RULE = ("`dim_basis` 为空的维度记 `null`（**无任何证据**）——**不参与**任何合计："
             "既不计入已测维度均值，也不作为 `1` 计入分母，并在真源里进 `unmeasured_dims`。"
             "页面上的 `1..5` 都表示「**有基座**」（该维挂了 ≥1 条证据）：`1` 是最低档、`5` 是最高档；"
             "**1–4 级的机械门槛都只是「基座非空」**——数字读数**不是** 1–4 级的必要条件，"
             "某维有没有可核数字读数由**证据档位**列（none／prose／reading／repro）另行披露。"
             "两者不是一回事（v1 把「未知」与「最低档」混记成 1，使覆盖率低的记录被系统性低估）。")

#: 未测项处理条款（页面用；验收标准要求显式写「未测 ＋ 原因」）。
UNMEASURED_RULE = ("**未测项**：凡本子站未取得原始输出的维度或子项，一律在详情页「未测」节"
                   "**显式写「未测 ＋ 原因」**——留空、或用「应该没问题」代替，视为未交付。"
                   "`dim_basis` 为空的维度（**无任何证据**）在真源里记 `null`、并进 `unmeasured_dims`，"
                   "**不参与**任何合计；页面上的 `1..5` 都表示**有基座**，`1` 是最低档，与「未测」是两回事——"
                   "**1–4 级的机械门槛都只是「基座非空」**，数字读数**不是** 1–4 级的必要条件"
                   "（有没有可核数字读数由**证据档位**列另行披露）；"
                   "旧口径把「未知」与「最低档」混记成同一个 1 再求和，正是本次要废掉的口径。")

#: 方法页「未测项怎么处理」小节标题（单列成常量：定点变异可用它换标记，从而证明该方法页确实在讲未测项）。
UNMEASURED_HEAD = "三、未测项怎么处理"

#: 证据档位说明（榜面／方法页用）：**只披露、不参与排序**——折价由读者做，不由本站替读者打折。
TIER_RULE = ("证据档位由 `dim_basis` 指向的证据**机械推导**：`none`（无证据）／"
             "`prose`（有证据但无数字读数）／`reading`（有可核数字读数）／`repro`（有本机复跑证据）。"
             "档位在榜面上**只披露、不参与排序**：它不折进分数、也不改变名次——"
             "要不要按证据强度折价由读者自己判，本站不替读者打折"
             "（打折需要新造一个系数，那属于**新造读数**）。")

#: 档位逐档含义（方法页／复核报告用；枚举与 `rubric.json.tiers` 同源）。
TIER_DESC = (
    ("none", "该维 `dim_basis` 为空——**未取得任何证据**（真源里该维记 `null`，并进 `unmeasured_dims`）。"),
    ("prose", "有证据，但 `output` 里**没有可核的数字读数**（判据见 `has_reading`：数字 ＋ 单位／百分比／`hit@k` 形态）。"),
    ("reading", "≥1 条证据的 `output` 含**可核的数字读数**；但该维 basis 里没有本机复跑条目。"),
    ("repro", "≥1 条证据的 `kind` 为**本机复跑**（其 `output` 与探针 stdout 逐字节相同，由 `evidence_check.py --repro` 每次复算）。"),
)

#: 零 LLM 判官条款（验收标准：禁用「看起来更好」「体验更佳」）。
NO_JUDGE_RULE = ("**零 LLM 判官**：本子站的每一条判定都能指回一条读数——"
                 "哪条读数支撑哪条结论逐项可指。禁用「看起来更好」「体验更佳」一类表述；"
                 "生成器本身也**不调用任何模型**、不发任何网络请求。")

#: 复现步骤（报告体例要求：环境、依赖、命令、预期耗时）。
REPRO_STEPS = (
    ("环境", "Python 3.12（与同仓其他脚本一致；`python -X utf8` 走 UTF-8）。"),
    ("依赖", "**零第三方依赖**——只用 Python 标准库（argparse／html／json／os／re／sys）。"),
    ("生成", "`python -X utf8 scripts/review_build.py`（写 `review/site/`）。"),
    ("判据复核", "`python -X utf8 scripts/review_build.py --rubric-report`"
                 "（逐维：分数 ↔ 档位 ↔ 支撑证据下标 ↔ 该级 must 是否满足 ↔ rationale）。"),
    ("守卫", "`python -X utf8 tests/test_review_build.py`（末行「通过 N / 失败 0」）。"),
    ("变异", "`python -X utf8 tests/test_review_build.py --mutate`（逐条恰好命中期望红项）。"),
    ("预期耗时", "生成 < 1 秒；守卫 < 5 秒；变异自证（逐条重跑守卫）< 60 秒。"),
    ("不触网", "以上命令**全程不发网络请求**；CI 里同样成立。"),
)

#: **可核数字读数**的单位白名单（`has_reading` 的判据面；与 `rubric.json.features.has_reading` 同口径）。
#: 顺序即正则交替序：长单位在前，避免 `bytes` 被 `B`、`tokens` 被 `tok` 截断。
READING_UNITS = ("%", "bytes", "B", "KB", "MB", "GB", "ms", "s",
                 "tok", "tokens", "条", "个", "次", "倍", "轮", "分")

#: 读数形状＝（数字）（可选小数）（可选的空白）（单位白名单之一）。**单位是必需的**——
#: 否则探针输出里的行号、sha256 十六进制串都会变成「读数」，档位判据就空转了。
READING_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|bytes|B|KB|MB|GB|ms|s|tok|tokens|条|个|次|倍|轮|分)")

#: `hit@<数字>` ／ `@<数字>` 形态（命中率读数的第二种写法，不跟单位也算读数）。
HIT_READING_RE = re.compile(r"(?:hit\s*@\s*\d+|@\d+)")


# ================================================================ 判据面（每条 = 一个可定点变异的函数）


# 生效条件：text 为任意值（含真源里来的不可信文本）时返回其 HTML 转义形态——真源内容一律先转义再进页面，防注入。
def esc(text) -> str:
    """HTML 转义（真源内容进页面前的唯一出口）。"""
    return html.escape(str(text), quote=True)


# 生效条件：text 为任意值时返回「先转义、再渲染行内 Markdown（粗体／行内代码）」的 HTML——**转义在前**，故不引入注入面。
def inline_md(text) -> str:
    """行内 Markdown 渲染（**粗体** → <b>，`代码` → <code>；先转义后替换，故不可注入）。"""
    out = esc(text)
    # 先把代码片段暂存进占位符，避免代码里的 ** 等标记被后续粗体正则误渲染。
    codes = []

    def _stash_code(m):
        codes.append("<code>%s</code>" % m.group(1))
        return "\x00CODE%d\x00" % (len(codes) - 1)

    out = re.sub(r"`([^`]+)`", _stash_code, out)
    out = re.sub(r"\*\*([^*]+)\*\*", lambda m: "<b>%s</b>" % m.group(1), out)
    for i, c in enumerate(codes):
        out = out.replace("\x00CODE%d\x00" % i, c)
    return out


# 生效条件：text 为任意值时返回「先转义、再把裸 URL 变可点链接」的 HTML——**转义在前**，故 href 不可能被注入改写。
def linkify(text) -> str:
    """把裸 URL 渲染成可点链接（先 esc 再替换；href 里只可能是已转义的 URL 文本）。"""
    out = inline_md(text)

    def _a(m):
        u = m.group(0)
        return '<a href="%s" rel="noopener noreferrer" target="_blank">%s</a>' % (u, u)

    return URL_IN_TEXT_RE.sub(_a, out)


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


# 生效条件：text 为任意值（真源里的 output 文本）时返回「其中是否有可核的数字读数」——
# 判据（守卫会钉住，**不许放宽**）：
#   output 含「(数字)(可选小数)(可选的空白)(单位)」，其中单位取自
#   % ／ bytes ／ B ／ KB ／ MB ／ GB ／ ms ／ s ／ tok ／ tokens ／ 条 ／ 个 ／ 次 ／ 倍 ／ 轮 ／ 分；
#   或含 `hit@<数字>` ／ `@<数字>` 形态。
# 为什么单位是必需的：行号（「第 215 行」）、sha256 十六进制串里到处是数字——
# 只认「有数字」，则任何探针输出都会被判成 reading，档位这条轴就失去分辨力。
def has_reading(text) -> bool:
    """「可核的数字读数」判据：数字 ＋ 单位白名单，或 `hit@k` ／ `@k` 形态。"""
    s = str(text or "")
    return bool(READING_RE.search(s) or HIT_READING_RE.search(s))


# 生效条件：path 为判据真源路径（None = RUBRIC_PATH）时返回其文档（dict）；缺失／JSON 坏／结构不符一律抛 ValueError（调用方 fail-closed）。
def load_rubric(path=None) -> dict:
    """读判据真源 `review/data/rubric.json`（fail-closed：读不到或结构不符即抛 ValueError）。"""
    p = path or RUBRIC_PATH
    try:
        with io.open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError("判据真源读取失败：%s（%s）" % (p, exc))
    if not isinstance(doc, dict):
        raise ValueError("判据真源结构不符（须为对象）：%s" % p)
    ver = doc.get("version")
    if not isinstance(ver, str) or not ver.strip():
        raise ValueError("判据真源缺 version（顶层非空字符串；真源的 rubric_version 须等于它）：%s" % p)
    dims = doc.get("dimensions")
    if not isinstance(dims, list) or tuple(str(x) for x in dims) != DIMENSIONS:
        raise ValueError("判据真源 dimensions 须与生成器 DIMENSIONS 完全一致且同序（%s）：%r"
                         % ("／".join(DIMENSIONS), dims))
    tiers = doc.get("tiers")
    if not isinstance(tiers, list) or tuple(str(x) for x in tiers) != TIERS:
        raise ValueError("判据真源 tiers 须恰为 %s：%r" % ("／".join(TIERS), tiers))
    levels = doc.get("levels")
    if not isinstance(levels, dict) or set(levels) != set(DIMENSIONS):
        raise ValueError("判据真源 levels 须覆盖且仅覆盖五维（%s）：%r"
                         % ("／".join(DIMENSIONS),
                            sorted(levels) if isinstance(levels, dict) else levels))
    feats = doc.get("features")
    if not isinstance(feats, dict) or not feats:
        raise ValueError("判据真源缺 features（must 里可用的特征名 → 机械判据）：%s" % p)
    want_levels = {str(n) for n in range(DIM_MIN, DIM_MAX + 1)}
    for k in DIMENSIONS:
        lv = levels[k]
        if not isinstance(lv, dict) or set(lv) != want_levels:
            raise ValueError("判据真源 levels[%s] 须恰含 %d–%d 五个级：%r"
                             % (k, DIM_MIN, DIM_MAX,
                                sorted(lv) if isinstance(lv, dict) else lv))
        for n in range(DIM_MIN, DIM_MAX + 1):
            spec = lv[str(n)]
            if not isinstance(spec, dict):
                raise ValueError("判据真源 levels[%s][%d] 须为对象：%r" % (k, n, spec))
            if not isinstance(spec.get("meaning"), str) or not spec["meaning"].strip():
                raise ValueError("判据真源 levels[%s][%d] 缺非空 meaning（人读的该级判据）" % (k, n))
            must = spec.get("must")
            if not isinstance(must, list) or not all(isinstance(f, str) for f in must):
                raise ValueError("判据真源 levels[%s][%d].must 须为特征名数组：%r" % (k, n, must))
            unknown = [f for f in must if f not in feats]
            if unknown:
                raise ValueError("判据真源 levels[%s][%d].must 含未定义特征名 %s（features 里没有）"
                                 % (k, n, "，".join(unknown)))
    return doc


# 生效条件：basis 为某维的 dim_basis 值、d 为记录时返回**真的解析得到**的证据条目列表——
# 越界下标、非整数下标一律跳过（校验面会点名拒收越界，这里只负责「不崩」）。
def _basis_entries(d, basis) -> list:
    """dim_basis 的原始下标 → 命中的证据条目（跳过越界／非整数）。"""
    ev = d.get("evidence")
    if not isinstance(ev, list):
        return []
    out = []
    for i in (basis if isinstance(basis, (list, tuple)) else []):
        if isinstance(i, bool) or not isinstance(i, int):
            continue
        if 0 <= i < len(ev) and isinstance(ev[i], dict):
            out.append(ev[i])
    return out


# 生效条件：d 为记录、basis 为该维证据下标列表时返回档位串（TIERS 之一）——档位的唯一判据。
def evidence_tier(d, basis) -> str:
    """由 `dim_basis`（证据下标列表）机械推导档位。

    basis 为空 -> "none"；其中 ≥1 条 kind == "本机复跑" -> "repro"；
    否则 ≥1 条 output 满足 has_reading() -> "reading"；否则（有证据但无数字读数）-> "prose"。
    """
    entries = _basis_entries(d, basis)
    if not entries:
        return "none"
    if any(str(e.get("kind") or "") == "本机复跑" for e in entries):
        return "repro"
    if any(has_reading(e.get("output")) for e in entries):
        return "reading"
    return "prose"


# 生效条件：d 为记录时返回 {维度名: 档位}（五维全给；null 维度给 "none"）——详情页／榜面共用。
def dim_tiers(d) -> dict:
    """五维档位表（`null` 维度恒为 "none"）。"""
    dims = d.get("dimensions")
    if not isinstance(dims, dict):
        dims = {}
    basis = d.get("dim_basis")
    if not isinstance(basis, dict):
        basis = {}
    return {k: ("none" if _dim_value(dims.get(k)) is None
                else evidence_tier(d, basis.get(k))) for k in DIMENSIONS}


# 生效条件：维度值 v 为真源 `dimensions[维度]` 的原值时返回整数分，`null`（或不可转值）返回 None。
def _dim_value(v):
    """真源维度值 → 整数分；`null` = 无任何证据 → None。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# 生效条件：d 为记录时返回已测得分列表（按 DIMENSIONS 顺序；null 与不可转值跳过）。
def _dim_scores(d) -> list:
    """已测维度的整数分（`null` = 无任何证据 → 不进这个列表）。"""
    dims = d.get("dimensions")
    if not isinstance(dims, dict):
        return []
    return [v for v in (_dim_value(dims.get(k)) for k in DIMENSIONS) if v is not None]


# 生效条件：d 为记录时返回非 null 的维度名列表（按 DIMENSIONS 顺序）——覆盖率与分母的唯一判据。
def measured_dims(d) -> list:
    """非 `null` 的维度名（按 DIMENSIONS 顺序）。"""
    return [k for k in DIMENSIONS
            if isinstance(d.get("dimensions"), dict)
            and _dim_value(d["dimensions"].get(k)) is not None]


# 生效条件：d 为记录时返回已测维度个数 0..5（null 维度不计）。
def coverage(d) -> int:
    """已测维度个数 0..5。"""
    return len(measured_dims(d))


# 生效条件：d 为记录时返回已测维度均值（round(x, 2)）；无已测维度返回 0.0。
def measured_mean(d) -> float:
    """已测维度均值（保留 2 位）；无已测维度 -> 0.0。"""
    vals = _dim_scores(d)
    return round(sum(vals) / len(vals), 2) if vals else 0.0


# 生效条件：d 为记录时返回已测维度之和；无已测维度返回 None（**不是** 0、更不是五维之和）。
def measured_total(d):
    """已测维度之和；无已测维度 -> None。"""
    vals = _dim_scores(d)
    return sum(vals) if vals else None


#: `total_score` 是 `measured_total` 的**旧名别名**（语义同此：无已测维度 → None）。
#: 保留名字是为了让既有调用点不必改锚——但它**不再是**「五维求和」：
#: 旧口径把未测维度的 `1` 一起相加，正是本次要废掉的缺陷。
total_score = measured_total


# 生效条件：feat 为 rubric 里的特征名、d 为记录、basis 为该维 dim_basis 时返回该特征是否被满足。
def _feature_ok(feat, d, basis) -> bool:
    """特征名 → 机械判据（未知名一律 fail-closed 视为未满足）。"""
    if feat == "has_any":
        return bool(isinstance(basis, (list, tuple)) and len(basis) >= 1)
    entries = _basis_entries(d, basis)
    if feat == "has_reading":
        return any(has_reading(e.get("output")) for e in entries)
    if feat == "has_repro":
        return any(str(e.get("kind") or "") == "本机复跑" for e in entries)
    return False


# 生效条件：d 为记录、rubric 为已载入判据时返回 [(维度, 分数, 缺失特征名), ...]——空列表 = 全过。
def level_must_ok(d, rubric) -> list:
    """该记录**所记级**的 must 逐条检查（`null` 维度跳过：其 must 不适用）。

    这是「5 分必须有本机复跑」的落点：rubric 的 `levels[维度][5].must` 含 `has_repro`，
    不满足即进返回列表，调用方（`validate_record`）逐条点名拒绝。
    """
    out = []
    if not isinstance(rubric, dict):
        return out
    levels = rubric.get("levels")
    levels = levels if isinstance(levels, dict) else {}
    dims = d.get("dimensions")
    dims = dims if isinstance(dims, dict) else {}
    basis = d.get("dim_basis")
    basis = basis if isinstance(basis, dict) else {}
    for k in DIMENSIONS:
        v = _dim_value(dims.get(k))
        if v is None:
            continue
        lv = levels.get(k)
        spec = lv.get(str(v)) if isinstance(lv, dict) else None
        if not isinstance(spec, dict):
            # 判据缺失也是「不满足」——fail-closed，绝不因为查不到判据就放行。
            out.append((k, v, "（判据缺失）"))
            continue
        must = spec.get("must")
        for feat in (must if isinstance(must, list) else []):
            if not _feature_ok(str(feat), d, basis.get(k)):
                out.append((k, v, str(feat)))
    return out


# 生效条件：d 为单个插件记录（dict）时返回错误串列表（空 = 该条合法）——逐条字段校验**只在本函数内**，故可被单独定点变异。
def validate_record(d) -> list:
    """单条插件记录的字段校验；返回点名错误（空列表 = 合法）。"""
    errs = []
    slug = str(d.get("slug") or "")
    tag = slug or str(d.get("name") or "?")
    for key in ("name", "slug", "version", "source_url", "reviewed_at",
                "dimensions", "dim_basis", "dim_rationale", "evidence",
                "conclusion", "boundary", "unmeasured"):
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
        dims = None
    else:
        for k, v in dims.items():
            if v is None:
                # `null` = 该维无任何证据（**不再**借 1 伪装成一个可以参与求和的分数）。
                continue
            if not isinstance(v, int) or isinstance(v, bool) or not (DIM_MIN <= v <= DIM_MAX):
                errs.append("%s 维度 %s 越界（须 null 或 %d–%d 整数）：%r"
                            % (tag, k, DIM_MIN, DIM_MAX, v))
    # 两轴分离的字段面：dim_basis（证据下标）与 dim_rationale（为什么是这个级）必须齐全，且键恰为五维。
    basis = d.get("dim_basis")
    if not isinstance(basis, dict) or set(basis) != set(DIMENSIONS):
        errs.append("%s dim_basis 须是「键恰为五维」的对象（%s）：%r"
                    % (tag, "／".join(DIMENSIONS), basis))
        basis = None
    rat = d.get("dim_rationale")
    if not isinstance(rat, dict) or set(rat) != set(DIMENSIONS):
        errs.append("%s dim_rationale 须是「键恰为五维」的对象（%s）：%r"
                    % (tag, "／".join(DIMENSIONS), rat))
        rat = None
    else:
        for k, v in rat.items():
            if not isinstance(v, str):
                errs.append("%s dim_rationale[%s] 须为字符串（实得 %s）——"
                            "否则页面会把 Python repr 当内容印出来" % (tag, k, type(v).__name__))
    # 无任何证据（`dim_basis` 为空）的维度必须记 null ＋ 进 unmeasured_dims；两处**双向**一致。
    um = d.get("unmeasured_dims")
    if um is None:
        errs.append("%s 缺 unmeasured_dims（无任何证据的维度列表；没有就写 []）" % tag)
        um = []
    elif not isinstance(um, list) or any(str(x) not in DIMENSIONS for x in um):
        errs.append("%s unmeasured_dims 须为维度名数组（可为空）：%r" % (tag, um))
        um = []
    if dims is not None and isinstance(um, list):
        um_set = {str(x) for x in um}
        if len(um_set) != len(um):
            errs.append("%s unmeasured_dims 有重复项：%r" % (tag, um))
        for k in [k for k in DIMENSIONS if k in dims and dims.get(k) is None]:
            if k not in um_set:
                errs.append("%s 维度 %s 无任何证据（dim_basis 为空，记 null）却没进 unmeasured_dims——"
                            "两处必须一致，否则「未测」既可能被漏报、也可能被当成一个可求和的分数" % (tag, k))
        for k in DIMENSIONS:
            if k in um_set and dims.get(k) is not None:
                errs.append("%s 维度 %s 有读数（%r）却列在 unmeasured_dims 里——"
                            "未测与已测在真源里必须双向一致：记 null ⇔ 列在 unmeasured_dims"
                            % (tag, k, dims.get(k)))
    ev = d.get("evidence")
    n_ev = len(ev) if isinstance(ev, list) else 0
    if dims is not None:
        for k in DIMENSIONS:
            v = _dim_value(dims.get(k))
            b = basis.get(k) if isinstance(basis, dict) else None
            if v is None:
                # null 维度的 basis 必须为空（不得指向证据）；rationale 允许写「为什么未测」。
                if isinstance(basis, dict) and not (isinstance(b, list) and not b):
                    errs.append("%s 维度 %s 无任何证据（null），dim_basis 必须为空数组"
                                "（不得指向任何证据）：%r" % (tag, k, b))
                continue
            if not isinstance(b, list) or not b:
                errs.append("%s 维度 %s 有读数（%r）却缺 dim_basis（须指向 ≥1 条证据）：%r"
                            % (tag, k, v, b))
            else:
                bad = [x for x in b if isinstance(x, bool) or not isinstance(x, int)
                       or not (0 <= x < n_ev)]
                if bad:
                    errs.append("%s 维度 %s 的 dim_basis 下标须为 range(%d) 内的整数（实得 %r）——"
                                "下标是证据的地址，越界即指不到读数" % (tag, k, n_ev, bad))
            r = rat.get(k) if isinstance(rat, dict) else None
            if not isinstance(r, str) or not r.strip():
                errs.append("%s 维度 %s 有读数（%r）却缺非空 dim_rationale——"
                            "每个非 null 维度都要写清它指回哪条具名证据、"
                            "以及为什么不是更高一级" % (tag, k, v))
            else:
                # ① 必须指回**具名证据**：「证据 N」里的 N 是 **1 基**编号，且须落在 1..len(evidence) 内。
                #    理由跳级的第一种坏法：压根不说这个分是从哪条读数来的。
                refs = [int(x) for x in re.findall(r"证据\s*(\d+)", r)]
                if not any(1 <= x <= n_ev for x in refs):
                    errs.append("%s 维度 %s 有读数（%r），但其 dim_rationale 未指回具名证据——"
                                "须含形如「证据 N」且 N 落在 1..%d 内（**1 基**编号）；实得：%r"
                                % (tag, k, v, n_ev, r[:90]))
                # ② 必须写明「为什么不是下一级」：分数 ≤ 4 时要求出现「未给 N／不给 N／不是 N」（N = 分数 + 1）。
                #    理由跳级的第二种坏法：说了分，却不说为什么不再高一档——读者无法判断是「证据不够」还是「没想到」。
                if v < DIM_MAX and not re.search(r"(?:未给|不给|不是)\s*%d" % (v + 1), r):
                    errs.append("%s 维度 %s 记 %d 分，但 dim_rationale 未写明「为什么不是下一级」——"
                                "须含形如「未给 %d」（或「不给 %d」／「不是 %d」）；实得：%r"
                                % (tag, k, v, v + 1, v + 1, v + 1, r[:90]))
    # 表现水平与证据必须对得上：所记级的 must 不满足即点名拒收（「5 分必须有本机复跑」的落点）。
    try:
        rubric = load_rubric()
    except ValueError as exc:
        errs.append("%s 判据真源不可用（fail-closed）：%s" % (tag, exc))
        rubric = None
    if rubric is not None:
        for k, v, feat in level_must_ok(d, rubric):
            errs.append("%s 维度 %s 记 %d 分，但该级必需证据特征 %s 未被 dim_basis 满足——"
                        "5 分的硬条件是**该维度有本机复跑证据**"
                        "（rubric：levels[%s][\"5\"].must 含 has_repro）" % (tag, k, v, feat, k))
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
    # 判据版本面：真源的 rubric_version 必须等于判据真源的 version——
    # 分数判据与读数各说各话时，页面上的分就无从复核，故 fail-closed。
    try:
        rubric = load_rubric()
    except ValueError as exc:
        return ["判据真源不可用（fail-closed，未写任何产物）：%s" % exc]
    rv = doc.get("rubric_version")
    if not isinstance(rv, str) or not rv.strip():
        errs.append("顶层缺 rubric_version（须等于 review/data/rubric.json 的 version：%s）"
                    % rubric.get("version"))
    elif rv != rubric.get("version"):
        errs.append("顶层 rubric_version=%r 与判据真源 version=%r 不一致——"
                    "两处口径必须同版，否则分数判据与读数各说各话" % (rv, rubric.get("version")))
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


# 生效条件：v 为分值（int／float）时返回其显示形态（round 到 2 位后的最短精确串：4／4.5／4.33）。
def _fmt_num(v) -> str:
    """分值显示形态（整数不带小数点，其余按 2 位）。"""
    return str(round(float(v), 2))


# 生效条件：n 为某条记录的算得分值（None = 该记录无已测维度）时返回榜面显示串——
# 榜面分值的**唯一**出口，便于单独钉住「榜面分数＝算得分数」。
def format_total(n) -> str:
    """榜面分值显示串（承载体：`<b>…</b>`；无已测维度给破折号）。"""
    if n is None:
        return '<span class="muted">—</span>'
    return "<b>%s</b>" % _fmt_num(n)


# 生效条件：d 为已校验的插件记录时返回 (本机复跑条数, 公开文档转引条数)——榜面「证据」列的唯一出口。
def kind_counts(d) -> tuple:
    """记录 → (本机复跑, 公开文档转引) 条数。"""
    ev = [e for e in (d.get("evidence") or []) if isinstance(e, dict)]
    n_local = sum(1 for e in ev if e.get("kind") == "本机复跑")
    return n_local, len(ev) - n_local


# 生效条件：d 为已校验的插件记录时返回 {档位: 该档维度数}——榜面档位列的唯一出口（五维计数合计恒为 5）。
def tier_counts(d) -> dict:
    """记录 → 五维的档位计数。"""
    tiers = dim_tiers(d)
    return {t: sum(1 for x in tiers.values() if x == t) for t in TIERS}


# 生效条件：counts 为 tier_counts() 的结果时返回榜面显示串（档位由强到弱、省略 0 档）。
def format_tiers(counts) -> str:
    """档位计数显示串（如 `repro 2 ／ reading 2 ／ prose 1`）。"""
    got = [t for t in reversed(TIERS) if (counts or {}).get(t)]
    return " ／ ".join("%s %d" % (t, counts[t]) for t in got) if got else "—"


# 生效条件：recs 为插件记录列表、rubric 为判据（当前不参与行结构，仅为调用方留口）时返回分段榜——
# {"ranked": [...], "insufficient": [...], "self": [...]}，三段各自按 _rank_key 排序。
def leaderboard(recs, rubric=None) -> dict:
    """真源 → 三段榜（他评榜／证据不足／自评）。

    分段：`ranked` = 他评且 coverage ≥ MIN_RANKED_COVERAGE；`insufficient` = 他评但 coverage 不足；
    `self` = self_review 为 true 的（不论 coverage）。行结构在原有
    {name, slug, version, source_url, total, record} 上追加 mean／coverage／tiers／self。
    """
    groups = {"ranked": [], "insufficient": [], "self": []}
    for d in recs:
        # ★本笔：**记录形状判据**。`recs` 来自 `review/data/plugins.json`（外部台账），
        # 元素非对象 ⇒ 下标 `d["name"]` 抛 `TypeError`/`KeyError`，**榜单整页出不来**。
        # `leaderboard` 是**榜单次序的唯一判据**（`render_board` / `render_pages` 都经它）。
        # （本轮量具修正**原样保留**上面这段上游已合入的判据，只把它顶上的
        #  「单列表 → 三段榜」这一处行结构改写；判据本身一字未动。）
        if not isinstance(d, dict):
            continue
        row = {"name": str(d["name"]), "slug": str(d["slug"]),
               "version": str(d["version"]),
               "source_url": str(d["source_url"]),
               "total": measured_total(d),
               "mean": measured_mean(d),
               "coverage": coverage(d),
               "tiers": dim_tiers(d),
               "self": bool(d.get("self_review")),
               "record": d}
        if row["self"]:
            groups["self"].append(row)
        elif row["coverage"] >= MIN_RANKED_COVERAGE:
            groups["ranked"].append(row)
        else:
            groups["insufficient"].append(row)
    for key in groups:
        groups[key].sort(key=_rank_key)
    return groups


# 生效条件：row 为榜单行时返回排序键（已测均值降序、覆盖率降序、插件名升序）——名次次序的唯一判据。
def _rank_key(row):
    return (-row["mean"], -row["coverage"], row["name"])


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
        '<code>review/data/plugins.json</code> ＋ <code>review/data/rubric.json</code> 机械生成'
        '——勿手改。本站只放可核验读数，<b>不涉资金</b>，<b>不采集用户隐私</b>。</footer>',
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


# 生效条件：recs 为插件记录列表时返回「已测均值 ／ 覆盖率」总览表（三段的次序与榜面一致）。
def overview_table(recs) -> str:
    """首页总览表（分母是**已测维度数**，不是 5——未测维度不进分母）。"""
    groups = leaderboard(recs)
    trs = []
    for label, key in (("他评榜", "ranked"), ("证据不足", "insufficient"), ("自评", "self")):
        for r in groups[key]:
            trs.append("<tr><td>%s</td><td><a href=\"detail_%s.html\">%s</a></td><td>%s</td>"
                       "<td>%s</td><td>%d/5</td></tr>"
                       % (label, esc(r["slug"]), esc(r["name"]), esc(r["version"]),
                          format_total(r["mean"]), r["coverage"]))
    if not trs:
        return '<p class="muted">（真源里没有插件记录——补齐 review/data/plugins.json 后本表自动出现。）</p>'
    return ("<table><tr><th>分段</th><th>插件</th><th>版本</th><th>已测均值</th><th>覆盖率</th></tr>"
            + "".join(trs) + "</table>")


# 生效条件：recs 为插件记录列表时返回首页 HTML（这是什么／怎么读表／分数总览／引用纪律／下一步）。
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
        "<li>先看 <a href=\"board.html\">榜单</a>：榜面报<b>已测维度均值</b>与<b>覆盖率</b>"
        "（已测维度数 ／ 5），<b>不再是</b>五维求和；他评榜／证据不足／自评分三段列。</li>",
        "<li>再点进<b>测评详情</b>：每维的<b>分 ＋ 证据档位 ＋ rationale</b>，"
        "以及每条证据的<b>命令与原始输出</b>、结论、边界。</li>",
        "<li><code>dim_basis</code> 为空（<b>无任何证据</b>）的项，在「未测」节<b>显式写「未测 ＋ 原因」</b>；"
        "真源里记 <code>null</code>，<b>不要</b>把它读成 0 分或最低分。页面上的 <code>1..5</code> 都表示"
        "<b>有基座</b>：<code>1</code> 是最低档——<b>1–4 级的机械门槛都只是「基座非空」</b>，"
        "数字读数不是 1–4 级的必要条件（有没有可核数字读数由<b>证据档位</b>列另行披露）。</li>",
        "<li>想看口径怎么定的（五维各量什么、两轴怎么分），去 <a href=\"method.html\">方法说明</a>。</li>",
        "</ol>",
        "<h2>分数总览（已测均值 ＋ 覆盖率）</h2>",
        '<div class="note">%s</div>' % inline_md(NULL_RULE),
        overview_table(recs),
        "<h2>引用纪律</h2>",
        "<ul>",
        "<li>每条证据必须写清 <b>命令 ＋ 原始输出 ＋ 来源</b>：三项缺一，生成器直接 fail-closed 拒绝出站。</li>",
        "<li>证据<b>分两档</b>，逐条在详情页顶部标出：<code>本机复跑</code>（由具名探针跑出，"
        "输出被 <code>evidence_check.py --repro</code> 逐字节复算）与 <code>公开文档转引</code>"
        "（取自公开文档原文读数，来源里给出 URL 与抓取日期——<b>不得</b>被读成本站本机重跑）。</li>",
        "<li><b>每条记录至少 1 条「本机复跑」</b>——只靠转引不算「命令 ＋ 原始输出」。这条由生成器强制。</li>",
        "<li>每个非 <code>null</code> 维度都要有 <code>dim_basis</code>（指向具体证据）与 "
        "<code>dim_rationale</code>（写清为什么不是更高一级）；判级依据取自 "
        "<code>review/data/rubric.json</code>。</li>",
        "</ul>",
        "<h2>复现步骤</h2>",
        "<table><tr><th>项</th><th>内容</th></tr>%s</table>" % rows,
        "<h2>下一步</h2>",
        '<p><a href="board.html">去榜单看已测维度均值与覆盖率</a> ｜ '
        '<a href="method.html">读方法说明：五维各量什么、两轴怎么分</a></p>',
        "",
    ])
    return page("首页", "index.html", body)


# 生效条件：rows 为 leaderboard 某一分段的行列表时返回该段表格 HTML——榜面分值的唯一出口经 format_total。
def board_table(rows) -> str:
    """一段榜（列：序号／插件／版本／已测均值／覆盖率／性质／证据（本机复跑 / 转引）／档位（五维计数）／来源）。"""
    if not rows:
        return '<p class="muted">（本段暂无记录）</p>'
    trs = []
    for i, r in enumerate(rows, 1):
        d = r["record"]
        n_local, n_quote = kind_counts(d)
        trs.append("<tr><td>%d</td><td><a href=\"detail_%s.html\">%s</a></td><td>%s</td>"
                   "<td>%s</td><td>%d/%d</td><td>%s</td><td>%d / %d</td><td>%s</td><td>%s</td></tr>"
                   % (i, esc(r["slug"]), esc(r["name"]), esc(r["version"]),
                      format_total(r["mean"]), r["coverage"], len(DIMENSIONS),
                      "自评" if r["self"] else "他评",
                      n_local, n_quote, esc(format_tiers(tier_counts(d))),
                      linkify(r["source_url"])))
    return ("<table><tr><th>#</th><th>插件</th><th>版本</th><th>已测均值</th><th>覆盖率</th>"
            "<th>性质</th><th>证据（本机复跑 / 转引）</th><th>档位（五维计数）</th><th>来源</th></tr>"
            + "".join(trs) + "</table>")


# 生效条件：recs 为插件记录列表时返回榜单 HTML（三段：他评榜／证据不足／自评；段内按已测维度均值降序）。
def render_board(recs) -> str:
    groups = leaderboard(recs)
    self_n = len(groups["self"])
    body = "\n".join([
        "<h2>榜单 · 已测维度均值降序</h2>",
        '<div class="note">%s</div>' % inline_md(NOTE_PENDING),
        "<p>计分口径：%s</p>" % inline_md(SCORE_RULE),
        '<div class="note">%s</div>' % inline_md(NULL_RULE),
        "<h3>他评榜</h3>",
        "<p class=\"muted\">他评且<b>覆盖率 ≥ %d/5</b> 的记录，按已测维度均值降序排"
        "（同均值按覆盖率降序，再按插件名升序）。</p>" % MIN_RANKED_COVERAGE,
        board_table(groups["ranked"]),
        "<h3>证据不足，暂不排名</h3>",
        "<p class=\"muted\">他评但<b>覆盖率 &lt; %d/5</b> 的记录：已测维度太少，"
        "均值由一两个读数决定，与满覆盖的记录并排会诱导误读，故门槛是<b>覆盖率 ≥ %d/5</b> 才进他评榜。"
        "它们不是「更差」，只是<b>证据更少</b>——请按明细自己判。</p>"
        % (MIN_RANKED_COVERAGE, MIN_RANKED_COVERAGE),
        board_table(groups["insufficient"]),
        "<h3>自评（作者同源）</h3>",
        ("<p class=\"muted\">当前 %d 条自评，<b>不论覆盖率单列于此</b>。"
         "<b>为什么分列</b>：自评与他评<b>不可等权混排</b>——同一支笔既写被评对象又写尺子时，"
         "名次会被读成独立评比的结论。<b>为什么不降权</b>：降权要乘一个系数"
         "（例如按自评身份打八折），而那个系数在真源里<b>没有任何读数</b>支撑——"
         "定它就是<b>新造读数</b>；本子站只放可核读数、不发明刻度。"
         "每条自评的详情页顶部都有利益相关声明。</p>" % self_n),
        board_table(groups["self"]),
        "<h2>证据档位（只披露，不参与排序）</h2>",
        '<div class="note">%s</div>' % inline_md(TIER_RULE),
        "<p class=\"muted\">榜面「档位（五维计数）」列照的类型（强→弱）："
        "<code>repro</code> = 该维有本机复跑证据；<code>reading</code> = 该维有可核数字读数；"
        "<code>prose</code> = 该维有证据但无数字读数；<code>none</code> = 该维无证据"
        "（即该维记 <code>null</code>、不参与合计）。</p>",
        "<h2>怎么看这个榜</h2>",
        "<p>榜面的「已测均值」只是<b><code>dim_basis</code> 非空（有基座）的那些维度</b>的均值，不是「谁更好」的总判决——"
        "<code>dim_basis</code> 为空的维度（无任何证据）记 <code>null</code>、<b>不参与</b>合计，故均值必须与<b>覆盖率</b>一起读："
        "同样是 4.5，覆盖 5/5 与覆盖 3/5 是两件事。"
        "不同插件面向的用法不同，请点进详情页对着<b>证据命令</b>自己判。</p>",
        "<p>同均值时按覆盖率降序、再按插件名升序排（次序稳定、可复现）。</p>",
        "",
    ])
    return page("榜单", "board.html", body)


# 生效条件：d 为单条插件记录时返回该插件的测评详情页 HTML（含 slug 锚点／维度表：分＋档位＋rationale／证据／结论／边界／未测）。
def render_detail(d) -> str:
    tiers = dim_tiers(d)
    basis = d.get("dim_basis") if isinstance(d.get("dim_basis"), dict) else {}
    rat = d.get("dim_rationale") if isinstance(d.get("dim_rationale"), dict) else {}
    dims = d.get("dimensions") if isinstance(d.get("dimensions"), dict) else {}
    dim_rows = []
    for k in DIMENSIONS:
        v = _dim_value(dims.get(k))
        b = [x for x in (basis.get(k) or [])
             if not isinstance(x, bool) and isinstance(x, int) and x >= 0]
        evs = "、".join("证据 %d" % (i + 1) for i in b)
        r = str(rat.get(k) or "")
        dim_rows.append("<tr><td>%s</td><td>%s</td><td><code>%s</code></td><td>%s</td><td>%s</td></tr>"
                        % (esc(k),
                           "未测" if v is None else "<b>%d</b>" % v,
                           esc(tiers[k]), esc(evs or "—"),
                           inline_md(r) if r else "—"))
    ev_blocks = []
    for i, e in enumerate(d["evidence"], 1):
        # ★本笔：**元素形状判据**。`d["evidence"]` 来自 `review/data/plugins.json`（外部台账），
        # 元素非对象 ⇒ `AttributeError`，详情页整页生不出来。
        # 可达性如实标注：`main()` 里 `validate(doc)` **先**跑，故 CLI 链上被拦住；
        # 但 `build(doc, out_dir)` 是公开入口、**仓内测试正是直接调它**，此时无人拦。
        if not isinstance(e, dict):
            ev_blocks.append("<h3>证据 %d <span class=\"tag\">（非对象条目）</span></h3>"
                             "<p class=\"muted\">该条目不是对象（实为 %s），跳过渲染。</p>"
                             % (i, esc(type(e).__name__)))
            continue
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
    nulls = [k for k in DIMENSIONS if _dim_value(dims.get(k)) is None]
    body = "\n".join([
        '<a id="%s"></a>' % esc(d["slug"]),
        "<h2>%s · 测评详情</h2>" % esc(d["name"]),
        "<p><span class=\"tag\">版本 %s</span>"
        "<span class=\"tag\">测评日 %s</span>"
        "<span class=\"tag\">已测均值 %s</span>"
        "<span class=\"tag\">覆盖率 %d/5</span>"
        "<span class=\"tag\">%s</span></p>"
        % (esc(d["version"]), esc(d["reviewed_at"]), _fmt_num(measured_mean(d)),
           coverage(d),
           "自评（作者同源）" if d.get("self_review") else "他评"),
        # 自评必须把利益相关摆在最前面，读者不该翻到底才发现。
        ("<div class=\"note\">%s</div>" % inline_md(d["disclosure"])
         if str(d.get("disclosure") or "").strip() else ""),
        "<p>来源：%s</p>" % linkify(d["source_url"]),
        "<p>版本面：%s（核对日 %s）</p>"
        % (linkify(d.get("version_source") or "（未声明）"),
           esc(d.get("version_checked_at") or "—")),
        "<h2>维度读数</h2>",
        '<div class="note">%s</div>' % inline_md(NULL_RULE),
        "<p class=\"muted\">判级依据是判据真源 <code>review/data/rubric.json</code> 的 "
        "<code>levels[维度][分数]</code>；「档位」由 <code>dim_basis</code> 指向的证据机械推导，"
        "只披露、不参与排序。</p>",
        "<table><tr><th>维度</th><th>分（1–%d；未测记 <code>null</code>）</th>"
        "<th>证据档位</th><th>支撑证据</th><th>dim_rationale（原文）</th></tr>%s</table>"
        % (DIM_MAX, "".join(dim_rows)),
        ("<p class=\"muted\"><code>dim_basis</code> 为空的维度（无任何证据，记 <code>null</code>，<b>不参与</b>合计）：%s</p>"
         % "、".join(esc(x) for x in nulls) if nulls else ""),
        "<p class=\"muted\">已测均值 %s（分母＝已测维度数 %d，不是 5）；覆盖率 %d/5。</p>"
        % (_fmt_num(measured_mean(d)), coverage(d), coverage(d)),
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


# 生效条件：rubric 为已载入判据时返回「五维 × 5 级」逐级可查的表 HTML（方法页第二节）。
def rubric_level_tables(rubric) -> str:
    """判据真源的逐维 5 级表（meaning 人读／must 机判）。"""
    blocks = []
    for k in DIMENSIONS:
        lv = rubric["levels"][k]
        rows = "".join(
            "<tr><td>%d</td><td>%s</td><td>%s</td></tr>"
            % (n, inline_md(lv[str(n)].get("meaning") or ""),
               inline_md("／".join(lv[str(n)].get("must") or []) or "（该级无 must）"))
            for n in range(DIM_MIN, DIM_MAX + 1))
        blocks.append("<h3>%s</h3>" % esc(k))
        blocks.append("<table><tr><th>级</th><th>该级的表现水平判据（人读）</th>"
                      "<th>该级的必需证据特征（机判）</th></tr>%s</table>" % rows)
    return "\n".join(blocks)


# 生效条件：recs 为插件记录列表时返回方法说明页 HTML（五维定义／两轴口径／未测项处理／证据档位／复现步骤）。
def render_method(recs) -> str:
    rubric = load_rubric()
    dim_rows = "".join("<tr><td>%s</td><td>%d–%d；<code>null</code> = 无任何证据</td></tr>"
                       % (esc(k), DIM_MIN, DIM_MAX) for k in DIMENSIONS)
    step_rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (esc(k), inline_md(v))
                        for k, v in REPRO_STEPS)
    feat_rows = "".join("<tr><td><code>%s</code></td><td>%s</td></tr>" % (esc(f), inline_md(v))
                        for f, v in sorted((rubric.get("features") or {}).items()))
    tier_rows = "".join("<tr><td><code>%s</code></td><td>%s</td></tr>" % (esc(t), inline_md(desc))
                        for t, desc in TIER_DESC)
    body = "\n".join([
        "<h2>〇、口径先说清</h2>",
        '<div class="note">%s</div>' % inline_md(NOTE_PENDING),
        "<h2>一、怎么读一条测评</h2>",
        "<p>一条测评 = ①维度读数（每维：<b>分</b>＋<b>证据档位</b>＋<b>rationale</b>）"
        " ②每条证据的<b>命令 ＋ 原始输出 ＋ 来源</b> ③结论 ④边界 ⑤未测项。"
        "缺任何一项，生成器在落盘前就拒绝（fail-closed）；"
        "落盘期失败（磁盘／权限）同样点名并以退出码 2 收场，不留半截站。</p>",
        "<p>每个非 <code>null</code> 维度必须带 <code>dim_basis</code>（指向具体证据的下标）与 "
        "<code>dim_rationale</code>（写清这个分指回哪条具名证据、以及<b>为什么不是更高一级</b>）；"
        "详情页把 rationale 原文一并印出。</p>",
        "<p>%s</p>" % inline_md(NO_JUDGE_RULE),
        "<h2>二、五维各量什么</h2>",
        "<p>下面逐维给出<b>判据真源</b> <code>review/data/rubric.json</code> 的 5 级定义："
        "「该级的表现水平判据」是人读的界线（写清了与相邻级的区别），"
        "「该级的必需证据特征」是生成器<b>机械判定</b>的硬条件——真源里某维记了某级、"
        "而 <code>dim_basis</code> 满足不了该级 must 时，生成器<b>逐条点名拒绝</b>、不落盘。</p>",
        rubric_level_tables(rubric),
        "<h3>证据特征：名字 → 机械判据</h3>",
        "<table><tr><th>特征名</th><th>判据</th></tr>%s</table>" % feat_rows,
        "<p class=\"muted\">分域（每维）：</p>",
        "<table><tr><th>维度</th><th>分域</th></tr>%s</table>" % dim_rows,
        "<h2>%s</h2>" % esc(UNMEASURED_HEAD),
        "<div class=\"note\">%s</div>" % inline_md(UNMEASURED_RULE),
        "<h2>四、证据来源的两档（<b>本子站把「可复跑」从「转引」里切出去</b>）</h2>",
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
        "它<b>不</b>证明被测评插件的运行时行为。<code>dim_basis</code> 为空（<b>无任何证据</b>）的维度，"
        "一律记 <code>null</code>（＝未测）并进 <code>unmeasured_dims</code>，再在「未测」节写明原因；"
        "<code>1..5</code> 都用于<b>有基座</b>的维度，<code>1</code> 是最低档——"
        "<b>1–4 级的机械门槛都只是「基座非空」</b>，数字读数不是 1–4 级的必要条件"
        "（有没有可核数字读数由<b>证据档位</b>列另行披露）。</div>",
        "<h2>五、两个正交的轴：表现水平 × 证据档位</h2>",
        "<p><b>轴一 · 表现水平</b>：<code>dimensions[维度]</code> = 1–5 整数"
        "（判据见上表「该级的表现水平判据」）；<code>null</code> = 该维<b>无法判级</b>"
        "（无任何证据）。</p>",
        "<p><b>轴二 · 证据档位</b>：%s——由 <code>dim_basis</code> 指向的证据"
        "<b>机械推导</b>（见下表与 <code>has_reading</code> 的判据）。</p>" % "／".join(TIERS),
        "<p>两轴<b>正交</b>：一个维度可以「档位高而水平低」（有可核读数，但读数本身是最低档），"
        "也可以「档位低而判断仍有据」（只有结构化描述、没有数字）。把两轴压成一个数，"
        "正是本子站 v1 的两个已确认缺陷：</p>",
        "<ol>",
        "<li><b>「未取得读数」伪装成 <code>1</code> 参与求和</b>——旧口径把 <code>1</code> "
        "同时当作「未知」与「最低档」，于是合计分不开「这一维没测」与「这一维测了但很差」，"
        "<b>覆盖率低的记录被系统性低估</b>（未测维度越多，被计入的那个 1 越多、合计越吃亏）。"
        "新口径：未测维度记 <code>null</code>、进 <code>unmeasured_dims</code>，"
        "<b>不参与</b>任何合计。</li>",
        "<li><b>合一了「表现水平」与「证据强度」两个正交的轴</b>——旧口径里，证据强度只能从"
        "分数高低里间接猜。新口径：档位在榜面单独披露，与分数并列可读。</li>",
        "</ol>",
        "<p><b>为什么是「分列」而不是「降权」</b>：降权要乘一个系数（例如按覆盖率或档位打几折），"
        "那个系数在真源里<b>没有任何读数</b>支撑——定它就是<b>新造读数</b>。"
        "本子站只放可核读数：均值、覆盖率、档位<b>摆出来</b>，要不要折价由读者自己判。</p>",
        "<p><b>5 级的硬条件</b>：该维度必须有<b>本机复跑证据</b>（<code>has_repro</code>）。"
        "这不是本次新增的要求——本子站 v1 起就写在方法页（「5 = 该维度上有可复跑证据且读数最好的一档」），"
        "本次只是把它落成 <code>rubric.json</code> 的 <code>levels[维度][\"5\"].must = "
        "[has_any, has_repro]</code>，由生成器机械判定，不满足即<b>逐条点名拒绝</b>。</p>",
        '<div class="note">%s</div>' % inline_md(SCORE_RULE),
        '<div class="note">%s</div>' % inline_md(NULL_RULE),
        "<table><tr><th>档位</th><th>含义与判据</th></tr>%s</table>" % tier_rows,
        '<div class="note">%s</div>' % inline_md(TIER_RULE),
        "<h2>六、复现步骤</h2>",
        "<table><tr><th>项</th><th>内容</th></tr>%s</table>" % step_rows,
        "",
    ])
    return page("方法说明", "method.html", body)


# 生效条件：recs 为已校验记录列表、rubric 为已载入判据时返回复核报告文本——
# 每条记录 × 每维：分数 ↔ 档位 ↔ 支撑证据下标 ↔ 该级 must 是否满足 ↔ rationale（供维护者一眼审）。
def rubric_report(recs, rubric) -> str:
    """逐维复核报告（`--rubric-report` 的唯一出口；只读、不落盘）。"""
    lines = ["判据真源：%s（version %s）" % (RUBRIC_PATH, rubric.get("version")),
             "档位枚举：%s ｜ 他评榜门槛：覆盖率 ≥ %d/5 ｜ 分数口径：已测维度均值（null 不参与合计）"
             % ("／".join(TIERS), MIN_RANKED_COVERAGE),
             ""]
    for i, d in enumerate(recs, 1):
        tiers = dim_tiers(d)
        basis = d.get("dim_basis") if isinstance(d.get("dim_basis"), dict) else {}
        rat = d.get("dim_rationale") if isinstance(d.get("dim_rationale"), dict) else {}
        dims = d.get("dimensions") if isinstance(d.get("dimensions"), dict) else {}
        lines.append("=== [%d] %s（%s；slug=%s）｜已测 %d/5 维｜已测均值 %s｜未测维度：%s ==="
                     % (i, d.get("name"), "自评" if d.get("self_review") else "他评",
                        d.get("slug"), coverage(d), _fmt_num(measured_mean(d)),
                        "、".join(unmeasured_dims_of(d)) or "（无）"))
        for k in DIMENSIONS:
            v = _dim_value(dims.get(k))
            b = basis.get(k) if isinstance(basis.get(k), list) else []
            r = str(rat.get(k) or "（空）")
            if v is None:
                lines.append("  - %s：分 null（未测）｜档位 %s｜支撑证据 []｜"
                             "must 不适用（null 维度跳过）" % (k, tiers[k]))
                lines.append("      rationale：%s" % r)
                continue
            spec = (rubric.get("levels") or {}).get(k, {}).get(str(v), {})
            must = spec.get("must") if isinstance(spec.get("must"), list) else []
            status = "；".join("%s=%s" % (f, "满足" if _feature_ok(str(f), d, b) else "**未满足**")
                               for f in must) or "（该级无 must 特征）"
            labels = "、".join("证据 %d" % (x + 1) for x in b if isinstance(x, int)) or "—"
            lines.append("  - %s：分 %d｜档位 %s｜支撑证据下标 [%s]（%s）｜must[%d]：%s"
                         % (k, v, tiers[k], ",".join(str(x) for x in b), labels, v, status))
            lines.append("      rationale：%s" % r)
        miss = level_must_ok(d, rubric)
        if miss:
            lines.append("  → must 总检：**未通过**——" + "；".join(
                "维度 %s 记 %d 分，缺特征 %s" % (k, v, f) for k, v, f in miss))
        else:
            lines.append("  → must 总检：全过")
        lines.append("")
    groups = leaderboard(recs)
    lines.append("分段：他评榜 %d 条 ／ 证据不足 %d 条 ／ 自评 %d 条"
                 % (len(groups["ranked"]), len(groups["insufficient"]), len(groups["self"])))
    for key, label in (("ranked", "他评榜"), ("insufficient", "证据不足"), ("self", "自评")):
        for j, row in enumerate(groups[key], 1):
            lines.append("  %s[%d] %s（slug=%s）｜已测均值 %s｜覆盖率 %d/5｜档位 %s"
                         % (label, j, row["name"], row["slug"], _fmt_num(row["mean"]),
                            row["coverage"], format_tiers(tier_counts(row["record"]))))
    return "\n".join(lines)


# 生效条件：d 为记录时返回未测维度名列表（`null` 的那些维度，按 DIMENSIONS 顺序；供复核报告显示）。
def unmeasured_dims_of(d) -> list:
    """未测维度名（`null` 的那些维度，按 DIMENSIONS 顺序）。"""
    dims = d.get("dimensions") if isinstance(d.get("dimensions"), dict) else {}
    return [k for k in DIMENSIONS if _dim_value(dims.get(k)) is None]


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
    ap.add_argument("--rubric-report", dest="rubric_report", action="store_true",
                    help="逐维复核报告（分 ↔ 档位 ↔ 支撑证据下标 ↔ 该级 must ↔ rationale）；"
                         "只打印、不落盘")
    args = ap.parse_args(argv)
    # 互斥标志：`--check` 只校验、`--print` 只打印，同时给等于没说清意图。
    # 同仓 `scripts/bounty_list.py` 同样先判 `--stdout` 再判 `--check`；此处**显式拒收**，
    # 免去「谁优先」的隐式口径（早先版本是 `--check` 静默压过 `--print`）。
    if args.check_only and args.print_only:
        sys.stderr.write("[错误] `--check` 与 `--print` 互斥：前者只校验产物，后者只打印不落盘；"
                         "请二选一。\n")
        return 2
    # `--rubric-report` 是**只读复核**：与「校验产物」「打印页面」都不是同一件事，同样拒收组合。
    if args.rubric_report and (args.check_only or args.print_only):
        sys.stderr.write("[错误] `--rubric-report` 与 `--check`／`--print` 互斥："
                         "前者只打印逐维复核报告，不落盘、也不比对产物。\n")
        return 2
    try:
        doc = load_data(args.data)
    except ValueError as exc:
        sys.stderr.write("[错误] %s\n" % exc)
        return 2
    if args.rubric_report:
        try:
            rubric = load_rubric()
        except ValueError as exc:
            sys.stderr.write("[错误] %s\n" % exc)
            return 2
        errs = validate(doc)
        if errs:
            sys.stderr.write("真源校验失败（fail-closed，未生成报告）：\n")
            for e in errs:
                sys.stderr.write("  - %s\n" % e)
            return 2
        sys.stdout.write(rubric_report(doc["records"], rubric) + "\n")
        return 0
    errs = validate(doc)
    if errs:
        sys.stderr.write("真源校验失败（fail-closed，未写任何产物）：\n")
        for e in errs:
            sys.stderr.write("  - %s\n" % e)
        return 2

    recs = doc["records"]
    if args.check_only:
        try:
            pages = render_pages(recs)
        except ValueError as exc:
            sys.stderr.write("[错误] 判据面不可用（fail-closed）：%s\n" % exc)
            return 2
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
