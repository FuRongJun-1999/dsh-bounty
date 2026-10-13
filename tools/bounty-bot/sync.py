# -*- coding: utf-8 -*-
"""同步引擎：拉结算表 + 悬赏，落库，落每日快照。

* 结算表：docs/bounty/贡献表.md（每天由账本机械生成）
* 悬赏：**本仓 issue**——标题以「悬赏」字样开头者即为一条悬赏委托
  （兼容 「悬赏 …」 与 「[悬赏] …」 两种前缀；PR 不算）

两条链路独立：单条失败不影响另一条。用指纹判「有无更新」；有更新才整表替换。
"""
from __future__ import annotations

import json
import re

import db
import github
import settle

#: 悬赏标题前缀（去空白后逐条比对；命中即入选）
BOUNTY_TITLE_PREFIXES = ("悬赏", "[悬赏]")

_PREFIX_RE = re.compile(r"^\s*(?:\[\s*悬赏\s*\]|悬赏)[\s:：\-—·、]*")


class SyncResult:
    def __init__(self):
        self.contrib_changed = False
        self.bounty_changed = False
        self.contrib_msg = ""
        self.bounty_msg = ""
        self.errors = []
        self.snapshot_n = 0

    def summary(self):
        parts = ["结算表：" + (self.contrib_msg or "未检查"),
                 "悬赏：" + (self.bounty_msg or "未检查")]
        if self.errors:
            parts.append("错误：" + "；".join(self.errors))
        return "\n".join(parts)


# ---------------------------------------------------------------- 结算表

def sync_contrib(conn, cfg, force=False):
    """同步结算表。返回 (是否有更新, 说明)。"""
    repo = cfg["repo"]
    branch = cfg.get("branch", "main")
    path = cfg["contrib_path"]
    token = cfg.get("github_token") or ""
    key = "contrib_sha"

    etag = None if force else db.meta_get(conn, key)
    code, text, new_etag = github.fetch_text(repo, path, branch, token, etag)
    if code == 304:
        return False, "已是最新（未变更）"

    issues, totals = settle.parse(text)
    if not totals:
        return False, "解析到 0 人，疑似表格结构变化，已跳过（保留旧数据）"

    declared = settle.grand_total(text)
    got = sum(t["total"] for t in totals)
    warn = ""
    if declared is not None and declared != got:
        warn += "（注意：表内声明总计 %s，实算 %s，有偏差）" % (declared, got)
    bad = settle.cross_check(issues, totals)
    if bad:
        warn += "（注意：%d 人每日增量与累计表不一致，明细仅作参考）" % len(bad)

    db.replace_contrib(conn, issues, totals)
    n = db.snapshot_contrib(conn)
    db.meta_set(conn, key, new_etag or "")
    db.meta_set(conn, "contrib_synced_at", db.now_iso())
    day = settle.day_of(text)
    if day:
        db.meta_set(conn, "contrib_day", day)
    return True, "已更新：%d 位贡献者 / %d 条明细，共 %d 分%s" % (
        len(totals), len(issues), got, warn)


# ---------------------------------------------------------------- 悬赏（issue）

def is_bounty_title(title):
    """标题是否以「悬赏」字样开头（悬赏 / [悬赏] 前缀）。"""
    return bool(_PREFIX_RE.match(title or ""))


def strip_bounty_prefix(title):
    """去掉前缀，留干净的任务标题。"""
    t = _PREFIX_RE.sub("", title or "", count=1).strip()
    return t or (title or "").strip()


def _label_names(issue):
    out = []
    for l in issue.get("labels") or []:
        if isinstance(l, dict):
            out.append(str(l.get("name") or ""))
        else:
            out.append(str(l))
    return [x for x in out if x]


def _pick(names, prefix):
    for n in names:
        if n.startswith(prefix):
            v = n.split(":", 1)[-1].strip()
            if v:
                return v
    return None


#: Markdown 图片 / 行内链接 / 粗斜体 / 行内代码 的轻量清洗（卡片是纯文本渲染）
_MD_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_MD_EMPH = re.compile(r"\*\*|__|(?<![\w*])\*|(?<![\w_])_")
_MD_CODE = re.compile(r"\x60([^\x60]*)\x60")
_MD_HR = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")


def plain_text(md):
    """Markdown -> 单行纯文本。

    卡片用的是 textContent，不会自己渲染 Markdown——不清洗就会把 **、[]() 原样显示。
    """
    t = _MD_IMG.sub("", md or "")            # 图片整体丢掉
    t = _MD_LINK.sub(r"\1", t)               # [文字](链接) -> 文字
    t = _MD_CODE.sub(r"\1", t)               # 行内代码
    t = _MD_EMPH.sub("", t)                   # **粗体** / *斜体* / _下划线_
    t = re.sub(r"^\s*>\s?", "", t)            # 引用
    return t.strip()


def issue_to_bounty(issue):
    """GitHub issue -> 悬赏记录（给 db.replace_bounties 用）。

    口径：**只要 issue 是 open，就一直算悬赏**——不按认领态（bounty:claimed /
    delivered / ...）过滤，标签只用来取难度，不改入选与状态。
    """
    names = _label_names(issue)
    difficulty = (_pick(names, "difficulty:") or "").lower() or None
    # 状态只反映 issue 本身的开闭，不跟随 bounty:* 认领态
    state = "open" if issue.get("state") == "open" else "closed"
    labels = [n for n in names if not n.startswith("difficulty:")]
    body = (issue.get("body") or "").strip()
    summary = ""
    for ln in body.splitlines():
        s = ln.strip()
        # 跳过标题 / 注释 / 分隔线 / 表格 / 纯符号行，取第一段有内容的正文
        if not s or s.startswith(("#", "<!--", "|", ">")) or _MD_HR.match(s):
            continue
        summary = plain_text(s)
        if summary:
            break
    if len(summary) > 120:
        summary = summary[:120] + "…"
    ms = issue.get("milestone")
    return {
        "bid": "issue-%s" % issue.get("number"),
        "no": str(issue.get("number") or ""),
        "title": plain_text(strip_bounty_prefix(issue.get("title"))),
        "difficulty": difficulty,
        "reward": None,
        "status": state,
        "deadline": (ms or {}).get("due_on") if isinstance(ms, dict) else None,
        "url": issue.get("html_url"),
        "note": summary or None,
        "labels": labels,
        "updated_at": issue.get("updated_at"),
    }


def parse_bounty_issues(issues, include_closed=False):
    """标题以「悬赏」开头的 issue -> 悬赏列表（默认只要 open）。

    入选只两条判据：① 标题以「悬赏」开头 ② issue 是 open（PR 不算）。
    **不看认领态标签**——open 就一直挂在板上，直到 issue 被关闭。
    """
    out = []
    for it in issues or ():
        if not isinstance(it, dict) or "pull_request" in it:
            continue
        if not is_bounty_title(it.get("title")):
            continue
        if not include_closed and it.get("state") != "open":
            continue
        out.append(issue_to_bounty(it))
    return out


def sync_bounty(conn, cfg, force=False):
    """从本仓 issue 同步悬赏。返回 (是否有更新, 说明)。"""
    bcfg = cfg.get("bounty") or {}
    repo = cfg["repo"]
    token = cfg.get("github_token") or ""
    if bcfg.get("enabled") is False:
        return False, "悬赏同步已关闭（config.bounty.enabled=false）"
    labels = bcfg.get("labels") or ""
    include_closed = bool(bcfg.get("include_closed"))

    issues, truncated = github.list_issues(
        repo, token, state="all" if include_closed else "open",
        labels=labels or None,
        per_page=int(bcfg.get("per_page", 100)),
        max_pages=int(bcfg.get("max_pages", 3)),
    )
    # 只要 open + 标题带「悬赏」——认领态标签（bounty:claimed 等）不参与筛选
    matched = [i for i in issues if is_bounty_title(i.get("title"))]
    fp = json.dumps(sorted(
        [str(i.get("number")), str(i.get("updated_at")), str(i.get("state")),
         ",".join(sorted(_label_names(i)))] for i in matched), ensure_ascii=False)
    key = "bounty_fp"
    if not force and db.meta_get(conn, key) == fp:
        return False, "已是最新（未变更）"

    items = parse_bounty_issues(matched, include_closed=include_closed)
    db.replace_bounties(conn, items)
    db.meta_set(conn, key, fp)
    db.meta_set(conn, "bounty_synced_at", db.now_iso())
    db.meta_set(conn, "bounty_source", "issues:标题前缀「悬赏」")
    tail = "（列表被截断，仅统计前 %d 条）" % len(issues) if truncated else ""
    if not items:
        return True, "已更新：当前没有标题带「悬赏」的开放 issue%s" % tail
    return True, "已更新：%d 条悬赏（来自 issue）%s" % (len(items), tail)


def sync_all(conn, cfg, force=False):
    """全量同步；单条失败不影响另一条。"""
    res = SyncResult()
    try:
        res.contrib_changed, res.contrib_msg = sync_contrib(conn, cfg, force)
    except github.GitHubError as exc:
        res.contrib_msg = "拉取失败"
        res.errors.append("结算表 " + str(exc))
    except Exception as exc:
        res.contrib_msg = "异常"
        res.errors.append("结算表 %s: %s" % (type(exc).__name__, exc))
    try:
        res.bounty_changed, res.bounty_msg = sync_bounty(conn, cfg, force)
    except github.GitHubError as exc:
        res.bounty_msg = "拉取失败"
        res.errors.append("悬赏 " + str(exc))
    except Exception as exc:
        res.bounty_msg = "异常"
        res.errors.append("悬赏 %s: %s" % (type(exc).__name__, exc))
    return res
