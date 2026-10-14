# -*- coding: utf-8 -*-
"""守卫：docs/reviews/ 下横向测评报告的「可复跑 + 可指认 + 不吹」机械核对。

为什么需要本件：测评报告的成立前提是「报告里的每个数字都能在原始日志里指到」，
且「没有读数的项被显式写成未测，而不是被静默算成好成绩」。这是**映射规则**，
不是排版细节，故必须可机械判定，且每条判据配一个**定点变异**自证（见 tests/test_check_reviews.py）。

判据（每条一个稳定 id）：
  R1  交付文件齐备：三家方案报告 + 测评方法论
  R2  方案报告逐字含七个必需二级标题（顺序一致）
  R3  方法论含 1-9 节 且五个具名标题逐字存在
  R4  报告/方法论里引用的每个 raw/<文件> 都真实存在
  R5  围栏代码块里的**读数行**必须在**该报告自己的证据桶**里逐字找到（防编造读数、防跨引擎贴条）
      证据桶＝ raw/ 下按归属切分的日志（`<引擎>_*`；类别收窄到 .txt/.json/.jsonl，
      `raw/*.sh` / `raw/*.py` 是复跑脚本，不是读数证据面）。
      跨引擎引用只有**显式归因**才放行：围栏**紧邻上方一行**点名 `raw/<文件>` ⇒ 该行可在那个
      文件里逐字核对；点名了却不 owning 该行，一样判红。
      `#` 前缀不再整类免检（注释/表头里出现读数形态且整行不可指 ⇒ 判红）。
  R6  禁用「无读数判官词」（零 LLM 判官）
      （R4/R5/R6/R13/R14 覆盖全部交付文档：三份方案报告 ＋ 测评方法论）
  R7  方案报告 2 节含一条可原样执行的复跑命令（python3 -X utf8 ... runner.py）；
      该节标题在正文区里必须**唯一**，缺失/重复 ⇒ 直接判红并点名
  R8  声称与证据一致（**fail-closed**）：summary 里每个模式记录都必须自带一枚**64 位十六进制
      sha256 指纹**，且 `matches_golden` 是布尔。三条判据：
      · 记录不是对象 / 缺 sha256 / 指纹不是 64 位十六进制 ⇒ **判红点名**；唯一的放行通道是
        报告里**同一行**同时出现该模式名与「未产出/无指纹/未落盘」的显式声明——
        静默通过等于把未披露的不一致算成好成绩（旧版就是这条 fail-open 路径）；
      · `matches_golden` 非布尔（缺失 / 字符串 / null）⇒ 判红；
      · `matches_golden` 为 false ⇒ 报告里必须**同一行**同时出现该模式名与
        「不一致/match=False/matches_golden…False」（全篇随便出现「不一致」不算）。
      另：summary 缺 `modes` / `modes` 不是对象 / `modes` 为空 ⇒ 同样判红（一个记录都没有
      ⇒ 逐模式判据无从核对，不许算通过）。
  R9  黄金产物指纹：data/out_baseline.jsonl 的实际 sha256 必须出现在方法论的**正文**里
      （围栏样例行不算：那是 raw 日志的复述，可被 R5 覆盖；若两者都算，只改正文的
      定点变异会被围栏副本掩盖 ⇒ 判据空转）
  R10 方案报告 6 节写了未测项（含「未测」且正文 >=40 字符）
  R11 方案报告 5 节写了不适用条件（正文 >=40 字符）
  R12 结论逐项可指：0 节结论摘要里每个编号/项目条目都带 M1-M8 引用，且至少引用 3 个不同读数项
      （R7/R10/R11/R12 的节切分走 section_body_ex()：只认**正文区**里与目标标题逐字相等且
      **唯一**的那一节，切尾边界也只在正文区里找；标题 0 次或 ≥2 次 ⇒ 该条判红并点名。
      围栏里的 `## …` 只是样例内容，不算标题。为什么必须这样：旧实现用 text.find() 取首次
      出现，在 §5 尾巴埋一个假 `## 6. 未测项与原因` ＋ ≥40 字填充、再把真 §6 清空成「无。」
      就能全绿。这条与 R5/R9 共用同一份围栏状态机 scan_lines()。）
  R13 声称出处与证据一致：`raw/<文件>` 引用所在行的标识符型读数 token 必须真在该文件里
      （R5 的池子是**该报告的证据桶**、且只认围栏行；R13 把读数绑到它**自己声称的那个文件**，
      围栏内外一视同仁——正文/表格里的「标识符 + 值」形态由它兜住；
      如实写「未落盘」的 token 豁免——声明不落盘不算编造）。
  R14 正文（围栏之外）里的读数同样必须逐字可指：
      (a) 正文里**整行复述原始日志行**的行（行首即读数键）必须逐字出现在证据桶里；
      (b) 方案报告**正文里出现的 64 位十六进制摘要**必须在证据桶文本里逐字出现。
      为什么单列一条：R5 只看围栏，而报告绝大多数数字在正文/表格里——把伪造读数写在正文
      可整篇免检。方法论正文的黄金 sha 由 R9 单列覆盖，故 (b) 只作用于三份方案报告，
      否则 R9 的定点变异会同时打红两条判据（多红＝语义纠缠）。
      边界：正文里的**派生数字**（比值/差值/区间）不在本判据内；本判据只判「整行复述的原始
      日志行」与「摘要指纹」这两类**逐字可指**的读数。
      （R13 与 R14 是一条判据的两个面：R13 管「声称的出处是否 owning 该 token」＝取证面，
       R14 管「正文里的读数行/摘要是否可在证据里逐字找到」＝位置面；两条各自有定点变异。）

用法：
  python -X utf8 scripts/check_reviews.py                 # 正向：末行「通过 N / 失败 M」
  python -X utf8 scripts/check_reviews.py --quiet         # 只输出 RED <id> / NOTE / RAN <n>
  python -X utf8 scripts/check_reviews.py --root <dir>    # 指定仓库根（变异体在沙箱里跑）
  python -X utf8 scripts/check_reviews.py --list          # 只列判据
退出码：0 = 全绿；1 = 有红项。

行为变更（相对改前）：
  · `--quiet` 除 `RED <id>` 外会多打 `NOTE <id> <原因>（<文件>）` 行——标题缺失/重复这类
    **结构**缺陷、以及 R13 的「token 不在所声称文件里」都会点名到具体 token 与文件。
    NOTE 只解释「为什么红」，不参与 RED 集合与退出码；解析 RED 的调用方按前缀过滤即可。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)
FENCE = chr(96) * 3

SCHEME_REPORTS = {
    "LangGraph_v0.1.md": "langgraph",
    "LlamaIndex-Workflows_v0.1.md": "llamaindex",
    "txtai-Workflow_v0.1.md": "txtai",
}
METHOD_REPORT = "测评方法论_v0.1.md"

SCHEME_HEADINGS = [
    "## 0. 结论摘要",
    "## 1. 被测对象与版本",
    "## 2. 复现步骤",
    "## 3. 基线 vs 方案对照读数",
    "## 4. 读数明细",
    "## 5. 不适用条件",
    "## 6. 未测项与原因",
]
METHOD_HEADINGS = [
    "## 4. 读数项",
    "## 5. 公平性规则",
    "## 6. 复现步骤（第三方原样可跑）",
    "## 8. 不适用条件",
    "## 9. 未测项与原因",
]
BANNED = ["看起来更好", "体验更佳", "更优雅", "更强大", "大概是", "应该是", "感觉不错"]

#: R8 的两个「同一行披露」形态：模式名与标记必须**同行**（全篇出现标记不算，
#: 否则「口径不一致」这类无关句子会让判据空转）。
#: 旧版 R8 只在「有 sha256 且 matches_golden is False」时才判，缺字段记录被 `continue`
#: 静默放行 ⇒ 未披露的不一致被算成好成绩（fail-open，实测踩过）。
R8_MISMATCH_MARK = r"(?:不一致|match=False|match: False|matches_golden[^\n]*False)"
R8_MISSING_MARK = r"(?:未产出|无指纹|未落盘|未生成|no\s+sha256)"
SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")

#: 读数行的判据：出现在原始日志里、且**必须逐字可指**的行形态。
READING_RE = re.compile(
    r"(RUN mode=|\bSHA [0-9a-f]{64}|\bTRACE |\bATTEMPTS |\bCAPS |REEXECUTED|FIRST_ERROR"
    r"|ERROR_TEXT|\bTIMING |SUMMARY_WRITTEN|[0-9a-f]{64}"
    r"|\bLOC |GRAPH_LINEAR|GRAPH_FANOUT|COLD_START_IMPORT_MS|COMPILE_LINEAR_MS|COMPILE_FANOUT_MS|\bdu -sh )")
#: raw/ 证据文件引用（要求带扩展名，避免把 raw/<name>_* 这类通配写法误判成悬空引用）。
RAW_REF_RE = re.compile(r"raw/[A-Za-z0-9_.\-]+\.(?:txt|json|jsonl|sh|py|md|log)")
#: R13 用：反引号包起来的**全大写标识符型** token（`LOC` / `GRAPH_FANOUT` / `ATTEMPTS`…），
#: 小写/驼峰标识符（`while` / `Send` / `s_fanout`）与含 `=`、空格、括号、路径的片段不算「读数 token」——
#: 那些是散文里的代码提及或值，报告允许改写排版。
IDENT_TOKEN_RE = re.compile(r"`([A-Z][A-Z0-9_]{2,})`")
#: R13 的豁免声明标记：一行里写明「未落盘」⇒ 该行的标识符 token 视为**如实声明未落盘**
#: （声明不落盘不算编造；R13 只治「声称有出处、实际没有」）。
UNLANDED_MARK = "未落盘"
#: raw/ 里**可当读数证据**的类别。`raw/*.sh` / `raw/*.py` 是复跑脚本，
#: 其中的源码行不能当读数证据（否则「随便一行打印语句」也能给报告背书）。
EVIDENCE_EXT = (".txt", ".json", ".jsonl")
#: 围栏里允许出现、不必逐字可指的行（复跑命令 / 环境）。
CMD_PREFIX = ("python3", "pip ", "cd ", "export ", "PYTHONPATH", "$ ")
#: 注释与表头/分隔线**不是免检牌**。`#` 原先在 CMD_PREFIX 里 ⇒ 伪造读数加 `# ` 即免检；
#: 现在它们只按普通行核对（带读数形态且整行不可指 ⇒ 判红），表头 `|` / 分隔线 `---` 同理收窄。
SOFT_PREFIX = ("#", "|", "---")
#: R14(a) 的「整行复述原始日志行」形态：行首（可带 markdown 列表号）即读数键。
LOG_LINE_RE = re.compile(
    r"^(?:[-*+]\s+|\d+[.)]\s+)?(?:RUN mode=|\bSHA |\bTRACE |\bATTEMPTS |\bCAPS |\bTIMING "
    r"|REEXECUTED|\bFIRST_ERROR|ERROR_TEXT|SUMMARY_WRITTEN)")

PROSE, CODE, FENCE_DELIM = "prose", "code", "fence"

#: 判据「点名」的落点：标题缺失/重复时记一条给人看的诊断。不改 RED 集合、不改退出码，
#: 但 --quiet 的变异自证里也能看见**为什么**红（否则「少红」与「多红」只能靠猜）。
NOTES = []


def point(rid, why, fn):
    if why:
        NOTES.append("%s %s（%s）" % (rid, why, fn))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def evidence_files(raw_dir, engine):
    """某份报告的**证据桶**文件表：raw/ 下归属该引擎的日志（类别见 EVIDENCE_EXT）。

    engine=None ⇒ 全部引擎的并集：测评方法论是**跨引擎对照**文档，必须能引用任一家的原始日志；
    方案报告只认自己那一桶——否则「拿 A 引擎的读数冒充 B 引擎的读数」照样全绿。
    """
    out = []
    if not os.path.isdir(raw_dir):
        return out
    for fn in sorted(os.listdir(raw_dir)):
        p = os.path.join(raw_dir, fn)
        if os.path.isfile(p) and fn.endswith(EVIDENCE_EXT) and (engine is None or fn.startswith(engine + "_")):
            out.append(fn)
    return out


def raw_pool(raw_dir, engine):
    """归属分桶后的证据：(桶内非空行集合, 桶内全文, 桶文件表)。

    返回全文是为了 R14(b)：正文里的摘要可能出现在**句子中间**，只按整行比对会漏。
    """
    lines, chunks, files = set(), [], []
    for fn in evidence_files(raw_dir, engine):
        t = read_text(os.path.join(raw_dir, fn))
        files.append(fn)
        chunks.append(t)
        for line in t.splitlines():
            s = line.strip()
            if s:
                lines.add(s)
    return lines, "\n".join(chunks), files


def scan_lines(text):
    """**唯一**的围栏状态机：逐行判定该行属于正文 / 围栏内 / 围栏定界行。

    R5（围栏块）、R9（正文）与 R7/R10/R11/R12（节切分）三处判定**共用**这一份状态机。
    分叉的代价：旧 section_body() 用 text.find() 在**全文**里找标题，围栏里的样例 `## …`
    也被当成标题 ⇒ 在 §5 尾巴埋一个假 `## 6.` 头，判据就切到假节上，真节没人看。
    返回 [(行号, 行原文, 归属)]，归属取 "prose" / "code" / "fence"。
    """
    out, inside = [], False
    for i, line in enumerate(text.splitlines()):
        if line.strip().startswith(FENCE):
            out.append((i, line, FENCE_DELIM))
            inside = not inside
            continue
        out.append((i, line, CODE if inside else PROSE))
    return out


def fenced_blocks_with_origin(text):
    """围栏代码块 → [(块内行, 开栏围栏的 0 基行号)]。

    行号是给 R5 的**归因**用的：跨引擎引用必须由「紧邻上方一行」点名出处，没有行号就对不上。
    """
    blocks, cur, opened, start = [], [], False, 0
    for i, line, kind in scan_lines(text):
        if kind == FENCE_DELIM:
            if opened:
                blocks.append((cur, start))
                cur, opened = [], False
            else:
                opened, start = True, i
            continue
        if opened:
            cur.append(line)
    if cur:
        blocks.append((cur, start))
    return blocks


def fenced_blocks(text):
    """薄壳：只要块内行。"""
    return [b for b, _ in fenced_blocks_with_origin(text)]


def prose_only(text):
    """去掉围栏代码块后的正文（与 fenced_blocks()/节切分共用 scan_lines()）。

    R9 用它在**正文**里找黄金 sha：围栏里的样例行是 raw 日志的复述（可被 R5 覆盖），
    若把两者都算作「写明了黄金 sha」，那么只改正文一处的定点变异会被围栏里的副本掩盖
    ⇒ 判据空转（实测踩过）。
    """
    return "\n".join(line for _i, line, kind in scan_lines(text) if kind == PROSE)


def section_headings(text):
    """**正文区**（围栏之外）里所有二级标题：[(行号, 标题原文), ...]，按出现顺序。"""
    heads = []
    for i, line, kind in scan_lines(text):
        if kind != PROSE:
            continue
        s = line.rstrip()
        if s.startswith("## "):
            heads.append((i, s))
    return heads


def section_body_ex(text, heading):
    """结构化切段：返回 (该节正文, 点名原因)。结构问题不是「没有内容」，是判据红。

    规则：
      · 目标标题在**正文区**出现 0 次 ⇒ (None, "标题缺失…")
      · 在正文区出现 ≥2 次          ⇒ (None, "标题重复 N 次…")：重复标题本身就是报告的
        结构缺陷，不许「取首次出现」蒙过去（否则假头一埋，真节就无人看）
      · 恰好 1 次                    ⇒ (正文, None)
    切尾边界同样只在正文区里找：围栏里的 `## ` 是样例内容，不能当节边界。
    标题比较为**去掉行尾空白后逐字相等**（不是子串包含，不是前缀）。
    """
    lines = [line for _i, line, _k in scan_lines(text)]
    hits = [i for i, h in section_headings(text) if h == heading.rstrip()]
    if not hits:
        return None, "标题缺失：%s" % heading
    if len(hits) > 1:
        return None, "标题重复 %d 次（正文区）：%s" % (len(hits), heading)
    start = hits[0]
    end = len(lines)
    for i, _h in section_headings(text):
        if i > start:
            end = i
            break
    return "\n".join(lines[start + 1:end]), None


def section_body(text, heading):
    """薄壳（兼容旧签名）：缺失/重复 ⇒ None；要**点名**请用 section_body_ex()。"""
    body, _why = section_body_ex(text, heading)
    return body


def _file_cached(raw_dir, fn, cache):
    if fn not in cache:
        t = read_text(os.path.join(raw_dir, fn))
        cache[fn] = ({s.strip() for s in t.splitlines() if s.strip()}, t)
    return cache[fn]


def attributions(text, opener):
    """开栏围栏**紧邻上方**那一行里显式点名的 raw/<文件>（跨引擎引用的归因白名单）。

    为什么是「紧邻一行」而不是「整节」：整节放行会把整节豁免掉，判据就空转了；紧邻一行是
    「这段原文出自哪份日志」的最小可机械核对面（例：`以下为 raw/baseline_runner.txt 原文片段：`）。
    白名单只放宽到**那个文件**：行仍必须在那份文件里逐字存在，否则一样判红——贴条者必须点名出处，
    而点名之后伪造行依然过不了。
    """
    lines = text.splitlines()
    for j in range(opener - 1, max(-1, opener - 4), -1):
        s = lines[j].strip()
        if s:
            return {os.path.basename(r) for r in RAW_REF_RE.findall(s)}
    return set()


def line_citable(s, raw_dir, pool, extra, cache):
    """整行逐字可指：先查本桶行集合，再查**显式归因**点名的文件。"""
    if s in pool:
        return True
    return any(s in _file_cached(raw_dir, fn, cache)[0] for fn in extra)


def digest_citable(d, raw_dir, pool_text, extra, cache):
    """摘要逐字可指：在证据桶全文（含句中）或归因点名的文件里出现。"""
    if d in pool_text:
        return True
    return any(d in _file_cached(raw_dir, fn, cache)[1] for fn in extra)


def scan_fenced_readings(text, raw_dir, engine, red):
    """R5：围栏里的读数行必须在证据桶里逐字可指（跨引擎需紧邻上方显式归因）。"""
    pool, _text, bucket = raw_pool(raw_dir, engine)
    cache = {}
    for block, opener in fenced_blocks_with_origin(text):
        extra = sorted(attributions(text, opener) - set(bucket))
        for line in block:
            s = line.strip()
            if not s:
                continue
            if s.startswith(SOFT_PREFIX):
                # 注释 / 表头 / 分隔线：不是免检牌——带读数形态且整行不可指 ⇒ 按编造判红
                if READING_RE.search(s) and not line_citable(s, raw_dir, pool, extra, cache):
                    red.add("R5")
                continue
            if s.startswith(CMD_PREFIX):
                continue
            if READING_RE.search(s) and not line_citable(s, raw_dir, pool, extra, cache):
                red.add("R5")


def scan_prose_readings(text, raw_dir, engine, red, digests=True):
    """R14：正文（围栏之外）里的读数同样必须逐字可指。

    (a) 整行复述原始日志行的行 ⇒ 整行必须在证据里逐字存在；
    (b) digests=True 时，正文里的 64 位十六进制摘要 ⇒ 必须在证据桶全文里逐字出现
        （方法论关掉 (b)：它的黄金 sha 由 R9 单列覆盖，两条都判会变成语义纠缠）。
    """
    pool, pool_text, bucket = raw_pool(raw_dir, engine)
    cache = {}
    for line in prose_only(text).splitlines():
        s = line.strip()
        if not s:
            continue
        extra = sorted({os.path.basename(r) for r in RAW_REF_RE.findall(s)} - set(bucket))
        if LOG_LINE_RE.match(s) and not line_citable(s, raw_dir, pool, extra, cache):
            red.add("R14")
        if digests:
            for d in sorted(set(re.findall(r"[0-9a-f]{64}", s))):
                if not digest_citable(d, raw_dir, pool_text, extra, cache):
                    red.add("R14")


def unlanded_tokens(text):
    """显式声明「未落盘」的行上出现的标识符 token —— R13 的豁免集。

    依据：如实声明「该段输出未随仓落盘」不算编造读数；R13 只治「声称有出处、实际没有」。
    """
    out = set()
    for line in text.splitlines():
        if UNLANDED_MARK in line:
            out.update(IDENT_TOKEN_RE.findall(line))
    return out


def r13_findings(text, raw_dir):
    """R13 的**点名明细**：[(标识符 token, 所声称的文件名), ...]。

    为什么把明细单列出来：R13 的违规是「某行声称 token 见 `raw/<file>`，而那个文件里没有它」，
    只报一个 `RED R13` 说不清是哪一条读数——`--quiet` 的 NOTE 行要能直接指到 token 与文件。
    """
    out, seen = [], set()
    exempt = unlanded_tokens(text)
    for line in text.splitlines():
        m = RAW_REF_RE.search(line)
        if not m:
            continue
        fn = os.path.basename(m.group(0))
        target = os.path.join(raw_dir, fn)
        if not os.path.isfile(target):
            continue  # 引用文件不存在由 R4 管
        body = read_text(target)
        for tok in IDENT_TOKEN_RE.findall(line):
            if tok in exempt or tok in body:
                continue
            if (tok, fn) in seen:
                continue
            seen.add((tok, fn))
            out.append((tok, fn))
    return out


def r13_red(text, raw_dir):
    """R13 声称出处与证据一致：`raw/<file>` 引用所在行的标识符型读数 token 必须真在该文件里。

    为什么需要它：R5 的池子是**该报告的证据桶**（跨引擎需显式归因）、且只认围栏行；
    报告里大量读数是正文/表格里的「标识符 + 值」形态，R5 一个都不核。
    R13 把「声称出处」与「证据文件」绑在一起：token 不在它自己声称的那个文件里 ⇒ 红。
    围栏内外一视同仁（声称出处的句子在哪都得算数）。
    """
    return bool(r13_findings(text, raw_dir))


def checks(root):
    ids = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12", "R13", "R14"]

    def run(r):
        reviews = os.path.join(r, "docs", "reviews")
        raw = os.path.join(r, "bench", "cross_eval", "raw")
        data = os.path.join(r, "bench", "cross_eval", "data")
        red = set()
        del NOTES[:]          # 每次判据运行独立（同一进程内多跑几轮也不串味）
        texts = {}
        for fn in list(SCHEME_REPORTS) + [METHOD_REPORT]:
            p = os.path.join(reviews, fn)
            texts[fn] = read_text(p) if os.path.isfile(p) else None

        for fn, t in texts.items():
            if t is None:
                red.add("R1")

        for fn, name in SCHEME_REPORTS.items():
            t = texts.get(fn)
            if t is None:
                # fail-closed：报告缺失时它的逐报告判据（含 R13/R14）一并红，不许静默跳过
                red.update(["R2", "R4", "R5", "R6", "R7", "R10", "R11", "R12", "R13", "R14"])
                continue
            pos, ok = -1, True
            for h in SCHEME_HEADINGS:
                i = t.find(h)
                if i < 0 or i <= pos:
                    ok = False
                    break
                pos = i
            if not ok:
                red.add("R2")
            for ref in set(RAW_REF_RE.findall(t)):
                if not os.path.exists(os.path.join(raw, os.path.basename(ref))):
                    red.add("R4")
            # R5：围栏读数按**本报告自己的证据桶**核对（跨引擎需显式归因）
            scan_fenced_readings(t, raw, name, red)
            # R14：正文（围栏之外）里的读数行/摘要同样逐字可指
            scan_prose_readings(t, raw, name, red, digests=True)
            # R13：声称出处与证据一致（正文/表格里的标识符型读数也要绑到它声称的那个文件）
            for tok, mfn in r13_findings(t, raw)[:3]:
                point("R13", "`%s` 不在所声称的 %s 里（且未声明未落盘）" % (tok, mfn), fn)
            if r13_red(t, raw):
                red.add("R13")
            if any(b in t for b in BANNED):
                red.add("R6")
            sec2, why2 = section_body_ex(t, "## 2. 复现步骤")
            point("R7", why2, fn)
            if not sec2 or not re.search(r"^python3 -X utf8 .*runner\.py", sec2, re.M):
                red.add("R7")
            sec5, why5 = section_body_ex(t, "## 5. 不适用条件")
            point("R11", why5, fn)
            if not sec5 or len(sec5.strip()) < 40:
                red.add("R11")
            sec6, why6 = section_body_ex(t, "## 6. 未测项与原因")
            point("R10", why6, fn)
            if not sec6 or "未测" not in sec6 or len(sec6.strip()) < 40:
                red.add("R10")
            sec0, why0 = section_body_ex(t, "## 0. 结论摘要")
            point("R12", why0, fn)
            sec0 = sec0 or ""
            items = [ln for ln in sec0.splitlines() if re.match(r"^\s*(?:[-*]|\d+[.)])\s+\S", ln)]
            mids = set(re.findall(r"M[1-8]", sec0))
            if (not items or len(mids) < 3
                    or any(not re.search(r"M[1-8]", ln) for ln in items)):
                red.add("R12")

        mt = texts.get(METHOD_REPORT)
        if mt is None:
            red.update(["R3", "R9"])
        else:
            for i in range(1, 10):
                if not re.search(r"^## %d\. " % i, mt, re.M):
                    red.add("R3")
            for h in METHOD_HEADINGS:
                if h not in mt:
                    red.add("R3")
            # 方法论里的基线读数同样必须可指认（R4/R5/R6/R13/R14 覆盖全部交付文档）
            for ref in set(RAW_REF_RE.findall(mt)):
                if not os.path.exists(os.path.join(raw, os.path.basename(ref))):
                    red.add("R4")
            # 方法论是跨引擎对照文档 ⇒ 证据桶取全部引擎的并集
            scan_fenced_readings(mt, raw, None, red)
            # R14(b) 不作用于方法论：它的黄金 sha 由 R9 单列覆盖（避免语义纠缠）
            scan_prose_readings(mt, raw, None, red, digests=False)
            # R13 同样覆盖方法论（基线读数也要绑到它声称的那份文件）
            for tok, mfn in r13_findings(mt, raw)[:3]:
                point("R13", "`%s` 不在所声称的 %s 里（且未声明未落盘）" % (tok, mfn), METHOD_REPORT)
            if r13_red(mt, raw):
                red.add("R13")
            if any(b in mt for b in BANNED):
                red.add("R6")
            gp = os.path.join(data, "out_baseline.jsonl")
            if not os.path.isfile(gp) or sha256_file(gp) not in prose_only(mt):
                red.add("R9")

        for fn, name in SCHEME_REPORTS.items():
            t = texts.get(fn)
            sp = os.path.join(raw, "%s_summary.json" % name)
            if t is None or not os.path.isfile(sp):
                red.add("R8")
                continue
            try:
                d = json.loads(read_text(sp))
            except ValueError:
                red.add("R8")
                continue
            if not isinstance(d, dict):
                red.add("R8")
                continue
            modes = d.get("modes") or {}
            if not isinstance(modes, dict) or not modes:
                # fail-closed：modes 不成形 / 一个模式都没有 ⇒ 逐模式判据无从核对，判红
                # （不许「没记录 = 没不一致 = 通过」——那正是缺字段即判通过的同一类漏洞）。
                red.add("R8")
                continue
            # 逐模式判据：某个模式在 summary 里 matches_golden=false 时，报告里必须有
            # **同一行同时出现该模式名与不一致标记**的披露（全篇出现「不一致」不算，
            # 否则「口径不一致」这类无关句子会让判据空转）。
            for mode, rec in sorted(modes.items()):
                # fail-closed：记录不成形 / 缺指纹 / 指纹不成形 ⇒ 判红，不再 `continue` 静默放行。
                if not isinstance(rec, dict):
                    red.add("R8")
                    continue
                sha = rec.get("sha256")
                if not (isinstance(sha, str) and SHA256_HEX_RE.match(sha)):
                    # 唯一放行通道：报告里**同一行**显式声明该模式未产出指纹。
                    pat = r"^.*\b%s\b.*%s.*$" % (re.escape(mode), R8_MISSING_MARK)
                    if not re.search(pat, t, re.M):
                        red.add("R8")
                    continue
                if not isinstance(rec.get("matches_golden"), bool):
                    red.add("R8")
                    continue
                if rec["matches_golden"] is False:
                    pat = r"^.*\b%s\b.*%s.*$" % (re.escape(mode), R8_MISMATCH_MARK)
                    if not re.search(pat, t, re.M):
                        red.add("R8")
        return red

    return ids, run


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    ids, run = checks(args.root)
    if args.list:
        for i in ids:
            print(i)
        return 0
    red = run(args.root)
    if args.quiet:
        for i in sorted(red):
            print("RED %s" % i)
        for n in NOTES:
            print("NOTE %s" % n)
        print("RAN %d" % len(ids))
        return 1 if red else 0
    print("检查根：%s" % os.path.abspath(args.root))
    if red:
        print("红项：%s" % sorted(red))
    for n in NOTES:
        print("NOTE %s" % n)
    print("通过 %d / 失败 %d" % (len(ids) - len(red), len(red)))
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
