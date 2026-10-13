# -*- coding: utf-8 -*-
"""贡献结算表解析（**新落点** v1.0）。

真源（仓内路径，每天更新）：
    docs/bounty/贡献表.md      <- 由 scripts/daily_table.py 从账本机械生成

表结构（实测 2026-10-12 版）：

  ## 2026-10-12（结算 13 项 · 合计 95 分）
  | # | 贡献者 | 项目 | 难度 | base | Δ | 影响 | 覆盖 issue | 依据 |
  | 1 | @LarryE135 | bounty_site | expert（round=1） | 10 | **10** | A | #24–#33 | ... |

  ### 按人合计
  | 贡献者 | 声誉分 | 项数 | 覆盖 issue |

  ## 累计（全部结算日）
  合计 **95** 分 · 13 项 · 7 位贡献者
  | 贡献者 | 声誉分 | 项数 | 覆盖 issue |
  | @LarryE135 | **28** | 4 | #12 ... |

★ 口径：声誉分取「累计」表为准（无该节时回落最后一次「按人合计」）；
  每日表的 Δ 列是该条交付的**当次增量**，用于 issue 级明细（项目/难度/影响/依据）。
  两者在正常账本下必然自洽——cross_check() 供自检，不自洽只告警、不阻断。
"""
from __future__ import annotations

import re

_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")

#: 难度裸值
_DIFFS = ("easy", "medium", "hard", "expert")

#: 旧版（v0.1）难度列是纯英文，新版是「expert（round=1）」——两种都认
_RE_ROUND = re.compile(r"round\s*=\s*(-?\d+)")


def _cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_row(line):
    s = line.strip()
    return s.startswith("|") and not _SEP.match(s)


def _int(text):
    if text is None:
        return None
    m = re.search(r"-?\d+", str(text).replace(",", ""))
    return int(m.group()) if m else None


def _clean(text):
    if text is None:
        return None
    t = str(text).strip()
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"`(.+?)`", r"\1", t)
    t = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", t)
    t = t.replace("❓", "").strip()
    return t or None


def _login(text):
    """贡献者列 -> 规范登录名（去 @ / 去粗体 / 去空格）。"""
    t = _clean(text)
    if not t:
        return None
    return t.lstrip("@").strip() or None


def _difficulty(text):
    """难度列 -> 裸值。形如 expert（round=1） / hard / difficulty:expert。"""
    t = (_clean(text) or "").lower()
    if not t:
        return None
    for d in _DIFFS:
        if d in t:
            return d
    return None


def _round_no(text):
    """难度列里的 round= 值（缺省 None）。"""
    m = _RE_ROUND.search(_clean(text) or "")
    return int(m.group(1)) if m else None


#: 区间展开上限——防「#1–999999」这类写法把列表撑爆（超限只取端点）
_MAX_RANGE = 200

_RANGE_RE = re.compile(r"#?\s*(\d+)\s*[–—~-]\s*#?\s*(\d+)")


def _issues_in(text):
    """从「覆盖 issue」列取出全部 issue 号（去重、保序；`#24–#33` 会展开）。"""
    t = _clean(text) or ""
    out = []

    def add(n):
        if n not in out:
            out.append(n)

    for m in _RANGE_RE.finditer(t):
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        if b - a > _MAX_RANGE:
            add(str(a))
            add(str(b))
            continue
        for n in range(a, b + 1):
            add(str(n))
    # 区间之外的孤立编号（如 "#18" / "#34 #44"）
    stripped = _RANGE_RE.sub(" ", t)
    for m in re.finditer(r"#?\s*(\d+)", stripped):
        add(m.group(1))
    return out


def _section(lines, *titles):
    """截取某个 ## 标题之后的正文行，直到下一个 ## 标题。titles 为空 => 全文。"""
    if not titles:
        return list(lines)
    out, inside = [], False
    for ln in lines:
        if re.match(r"^#{1,3}\s", ln):
            head = re.sub(r"^#{1,3}\s*", "", ln).strip()
            inside = any(t in head for t in titles)
            continue
        if inside:
            out.append(ln)
    return out


def day_of(text):
    """返回表里最新的结算日（YYYY-MM-DD），无则 None。"""
    found = None
    for ln in (text or "").splitlines():
        m = re.match(r"^#{2,3}\s*(\d{4}-\d{2}-\d{2})", ln.strip())
        if m and found is None:
            found = m.group(1)
    return found


def parse_issues(text):
    """解析每日明细表 -> issue 级明细（跨全部结算日，按出现次序）。"""
    rows, header = [], None
    for ln in (text or "").splitlines():
        if re.match(r"^#{1,3}\s", ln):
            header = None          # 换节即换表头：防止把「按人合计」表头借来用
            continue
        if not _is_row(ln):
            continue
        cells = _cells(ln)
        if header is None:
            # 用 casefold 比较：`Δ`.lower() 会变成希腊 `δ`，用 lower() 会漏掉这一列
            header = [c.casefold() for c in cells]
            continue
        joined = " ".join(header)
        # 只认「贡献者 + 难度」同时在表头里的明细表（排除按人合计表）
        if "贡献者" not in joined or ("难度" not in joined and "difficulty" not in joined):
            continue

        def col(*names):
            for n in names:
                for i, h in enumerate(header):
                    if n.casefold() in h:
                        return cells[i] if i < len(cells) else None
            return None

        github = _login(col("贡献者", "提交者", "github"))
        if not github or github in ("合计", "总计"):
            continue
        diff_cell = col("难度", "difficulty")
        covers = _issues_in(col("覆盖 issue", "issue", "对应 issue"))
        issue_no = covers[0] if covers else (str(_int(col("#", "编号")) or "") or None)
        rec = {
            "issue_no": issue_no,
            "github": github,
            "project": _clean(col("项目", "project")),
            "difficulty": _difficulty(diff_cell),
            "round": _round_no(diff_cell),
            "base": _int(col("base", "基础")),
            "delta": _int(col("Δ", "delta", "声誉分")),
            "impact": _clean(col("影响", "impact")),
            "evidence": _clean(col("依据", "证据", "evidence")),
            "covers": covers,
        }
        if rec["github"] and rec["issue_no"]:
            rows.append(rec)
    return rows


def _by_person_block(lines, title):
    out, header = [], None
    for ln in _section(lines, title):
        if not _is_row(ln):
            continue
        cells = _cells(ln)
        if header is None:
            header = [c.casefold() for c in cells]
            continue
        name = _login(cells[0]) if cells else None
        if not name or name in ("贡献者", "合计", "总计"):
            continue
        total = _int(cells[1]) if len(cells) > 1 else None
        if total is None:
            continue
        out.append({
            "github": name,
            "total": total,
            "items": _int(cells[2]) if len(cells) > 2 else None,
            "issues": _clean(cells[3]) if len(cells) > 3 else None,
        })
    return out


def parse_days(text):
    """按**结算日**拆出每天的分数：{日期: [{github,total,items,issues}, ...]}。

    表里每节形如：
        ## 2026-10-12（结算 13 项 · 合计 95 分）
        | # | 贡献者 | ... |        <- 明细（当日交付）
        ### 按人合计
        | 贡献者 | 声誉分 | 项数 |   <- **当天的分**（不是累计）

    ★ 口径：这些分数就是「当天赚到的分」，**不需要再相减**。
    热力图直接按天记录，历史靠这里的日期分批落库。
    """
    lines = (text or "").splitlines()
    days, cur_date, buf = {}, None, []
    for ln in lines:
        m = re.match(r"^#{2,3}\s*(\d{4}-\d{2}-\d{2})", ln.strip())
        if m:
            if cur_date:
                days[cur_date] = _by_person_block(buf, "按人合计") or _by_person_block(buf, "")
            cur_date, buf = m.group(1), []
            continue
        if cur_date:
            buf.append(ln)
    if cur_date:
        days[cur_date] = _by_person_block(buf, "按人合计") or _by_person_block(buf, "")
    return {d: v for d, v in days.items() if v}


def parse_totals(text):
    """解析按人合计 -> 每人声誉分。

    优先「累计（全部结算日）」节；无该节时回落最后一次「按人合计」表。
    """
    lines = (text or "").splitlines()
    block = _by_person_block(lines, "累计")
    if block:
        return block
    return _by_person_block(lines, "按人合计")


def parse(text):
    """返回 (issues, totals)。"""
    return parse_issues(text), parse_totals(text)


_TOTAL_RE = re.compile(r"(?:合计|总计)\s*\**\s*(\d+)\s*\**\s*分")


def grand_total(text):
    """表里声明的**累计**总分（用于自检）。

    注意：每日小节的标题里也有「合计 N 分」（那是当日的），必须先认
    「累计（全部结算日）」节——否则会把最后一天的分数当成总分。
    """
    lines = (text or "").splitlines()
    tail = _section(lines, "累计")
    scope = tail if tail else lines
    found = None
    for ln in scope:
        for m in _TOTAL_RE.finditer(ln):
            found = int(m.group(1))
    return found


def cross_check(issues, totals):
    """逐人核对：每日 Δ 之和 vs 累计表。返回不一致清单（空 = 自洽）。"""
    per = {}
    for i in issues:
        k = i["github"].lower()
        per[k] = per.get(k, 0) + int(i.get("delta") or 0)
    bad = []
    for t in totals:
        k = t["github"].lower()
        if per.get(k) != int(t["total"]):
            bad.append((t["github"], per.get(k), int(t["total"])))
    return bad
