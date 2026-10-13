# -*- coding: utf-8 -*-
"""悬赏机器人 · 数据层（SQLite）。

设计要点
--------
* 一 QQ 一 GitHub、一 GitHub 一 QQ（双向唯一）——绑定表两个唯一索引。
* 贡献历史永不删除：contrib_snapshot 每天一版全量快照（append-only），
  热力图的「当日声誉分增量」由相邻两版快照求差得到。
* 悬赏热力图口径 = 每天获得的声誉分（不是 GitHub 提交数）。
* 悬赏来源 = 本仓 issue（标题带「悬赏」前缀），见 sync.py。
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

_LOCK = threading.Lock()

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- 绑定：一 QQ 一 GitHub（双向唯一）
CREATE TABLE IF NOT EXISTS bindings (
    qq          TEXT PRIMARY KEY,
    github      TEXT NOT NULL,
    github_cf   TEXT NOT NULL,
    bound_at    TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uix_bindings_github_cf ON bindings(github_cf);

-- 结算表明细（issue 级）
CREATE TABLE IF NOT EXISTS contrib_issue (
    github      TEXT NOT NULL,
    issue_no    TEXT NOT NULL,
    project     TEXT,
    difficulty  TEXT,
    base        INTEGER,
    delta       INTEGER,
    impact      TEXT,
    evidence    TEXT,
    synced_at   TEXT NOT NULL,
    PRIMARY KEY (github, issue_no)
);

-- 结算表按人合计
CREATE TABLE IF NOT EXISTS contrib_total (
    github      TEXT PRIMARY KEY,
    total       INTEGER NOT NULL,
    issues      TEXT,
    synced_at   TEXT NOT NULL
);

-- 每日快照（append-only，永不删除）——热力图数据源
--
-- ★ 语义：`total` = 该日的**累计声誉分**（存量）。
--   热力图口径 = **今天累计 − 昨天累计**（当日增量）。
--   跨来源（v0.1 -> 新贡献表）两套算法不可比，该日不产生增量，只作新基线。
--   src = 来源（'v0.1' 旧的 11 号 / 'ledger' 新的贡献表）。
CREATE TABLE IF NOT EXISTS contrib_snapshot (
    snap_date   TEXT NOT NULL,
    github      TEXT NOT NULL,
    total       INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    src         TEXT NOT NULL DEFAULT 'ledger',
    PRIMARY KEY (snap_date, github)
);

-- 悬赏（从本仓 issue 同步：标题带「悬赏」前缀）
CREATE TABLE IF NOT EXISTS bounty (
    bid         TEXT PRIMARY KEY,
    no          TEXT,
    title       TEXT NOT NULL,
    difficulty  TEXT,
    reward      TEXT,
    status      TEXT,
    deadline    TEXT,
    url         TEXT,
    note        TEXT,
    labels      TEXT,
    updated_at  TEXT,
    owner       TEXT,
    ord         INTEGER,
    synced_at   TEXT NOT NULL
);

-- 历史手动补录（**常年累加**）：初期 bootstrap 的分数（如 11 号 v0.1 表）
-- 这些不在当前贡献表里，但属于该成员已获得的分，故并入总榜/累计。
-- 与 contrib_total 分开存 => 每天同步整表替换 contrib_total 时不会把它冲掉。
CREATE TABLE IF NOT EXISTS contrib_history (
    github      TEXT PRIMARY KEY,
    total       INTEGER NOT NULL,
    src         TEXT,
    note        TEXT,
    added_at    TEXT NOT NULL
);

-- 同步元数据（sha / 指纹 / 上次时间）
CREATE TABLE IF NOT EXISTS sync_meta (
    k           TEXT PRIMARY KEY,
    v           TEXT,
    updated_at  TEXT
);
"""

#: 老库补列（列名 -> 建表语句片段）；缺失才 ALTER，幂等
_MIGRATIONS = {
    "bounty": {"labels": "TEXT", "updated_at": "TEXT",
               "owner": "TEXT", "ord": "INTEGER"},
    "contrib_snapshot": {"src": "TEXT NOT NULL DEFAULT 'ledger'"},
}


class BindConflict(RuntimeError):
    """该 GitHub 已被另一个 QQ 绑定（并发写入时由唯一索引兜住）。"""


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return date.today().isoformat()


def _migrate(conn):
    for table, cols in _MIGRATIONS.items():
        have = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if not have:
            continue
        for col, decl in cols.items():
            if col not in have:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))
    conn.commit()


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


# ---------------------------------------------------------------- 绑定

def get_binding(conn, qq):
    return conn.execute("SELECT * FROM bindings WHERE qq=?", (str(qq),)).fetchone()


def get_binding_by_github(conn, github):
    return conn.execute(
        "SELECT * FROM bindings WHERE github_cf=?", (str(github).strip().lower(),)
    ).fetchone()


def bind(conn, qq, github):
    """绑定/覆盖。返回 (动作, 被顶掉的原 github)。动作 in {created, rebound}。

    并发下若该 github 已被别的 qq 占住，唯一索引会拒绝——转成 BindConflict。
    """
    qq, github = str(qq), github.strip()
    gh_cf = github.lower()
    ts = now_iso()
    old = get_binding(conn, qq)
    try:
        with _LOCK, conn:
            conn.execute(
                "INSERT INTO bindings(qq, github, github_cf, bound_at, updated_at) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(qq) DO UPDATE SET github=excluded.github, "
                "github_cf=excluded.github_cf, updated_at=excluded.updated_at",
                (qq, github, gh_cf, ts, ts),
            )
    except sqlite3.IntegrityError as exc:
        raise BindConflict(str(exc)) from exc
    if old is None:
        return "created", None
    return "rebound", old["github"]


def unbind(conn, qq) -> bool:
    with _LOCK, conn:
        cur = conn.execute("DELETE FROM bindings WHERE qq=?", (str(qq),))
    return cur.rowcount > 0


# ---------------------------------------------------------------- 贡献

def replace_contrib(conn, issues, totals) -> None:
    """整表替换结算表明细与合计（快照不动）。"""
    ts = now_iso()
    with _LOCK, conn:
        conn.execute("DELETE FROM contrib_issue")
        conn.execute("DELETE FROM contrib_total")
        conn.executemany(
            "INSERT OR REPLACE INTO contrib_issue"
            "(github,issue_no,project,difficulty,base,delta,impact,evidence,synced_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            [
                (i.get("github", "").strip(), str(i.get("issue_no", "")), i.get("project"),
                 i.get("difficulty"), i.get("base"), i.get("delta"), i.get("impact"),
                 i.get("evidence"), ts)
                for i in issues if i.get("github")
            ],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO contrib_total(github,total,issues,synced_at)"
            " VALUES(?,?,?,?)",
            [
                (t.get("github", "").strip(), int(t.get("total") or 0),
                 t.get("issues"), ts)
                for t in totals if t.get("github")
            ],
        )


def snapshot_contrib(conn, snap_date=None, src="ledger", pairs=None) -> int:
    """落一版**累计分**快照（同日重复同步覆盖当日，不改历史日）。

    pairs 给定时用它；否则取 contrib_total（当日表的按人合计 = 累计分）。
    src 记录来源（ledger = 新贡献表）。历史日的快照**绝不删除**。
    """
    snap_date = snap_date or today()
    ts = now_iso()
    if pairs is None:
        pairs = [(r["github"], int(r["total"]))
                 for r in conn.execute("SELECT github, total FROM contrib_total")]
    rows = [(snap_date, str(g).strip(), int(t), ts, src)
            for g, t in pairs if str(g).strip()]
    if not rows:
        return 0
    with _LOCK, conn:
        conn.executemany(
            "INSERT INTO contrib_snapshot(snap_date,github,total,captured_at,src)"
            " VALUES(?,?,?,?,?) "
            "ON CONFLICT(snap_date,github) DO UPDATE SET total=excluded.total,"
            " captured_at=excluded.captured_at, src=excluded.src",
            rows,
        )
    return len(rows)


def seed_snapshot(conn, snap_date, pairs, src="ledger") -> int:
    """直接写一版快照（补录历史用）。pairs = [(github, total), ...]。

    与 snapshot_contrib 的区别：数据不从 contrib_total 来，便于补 11/12 号这类
    已经不在当前表里的历史。
    """
    ts = now_iso()
    rows = [(snap_date, str(g).strip(), int(t), ts, src)
            for g, t in pairs if str(g).strip()]
    if not rows:
        return 0
    with _LOCK, conn:
        conn.executemany(
            "INSERT INTO contrib_snapshot(snap_date,github,total,captured_at,src)"
            " VALUES(?,?,?,?,?) "
            "ON CONFLICT(snap_date,github) DO UPDATE SET total=excluded.total,"
            " captured_at=excluded.captured_at, src=excluded.src",
            rows,
        )
    return len(rows)


def person_detail(conn, github):
    """某个 github 账户的完整贡献明细（大小写不敏感）。

    total = 当前表分 ＋ 历史补录分（与总榜口径一致）。
    """
    cf = github.strip().lower()
    total_row = conn.execute(
        "SELECT * FROM contrib_total WHERE lower(github)=?", (cf,)
    ).fetchone()
    hist = conn.execute(
        "SELECT total,src FROM contrib_history WHERE lower(github)=?", (cf,)
    ).fetchone()
    issues = conn.execute(
        "SELECT * FROM contrib_issue WHERE lower(github)=? ORDER BY CAST("
        "REPLACE(REPLACE(issue_no, '#', ''), ' ', '') AS INTEGER)",
        (cf,),
    ).fetchall()
    if total_row is None and hist is None and not issues:
        return None
    if total_row is not None:
        base = int(total_row["total"])
        name = total_row["github"]
        itext = total_row["issues"]
    elif issues:
        base = sum(int(i["delta"] or 0) for i in issues)
        name = issues[0]["github"]
        itext = None
    else:
        base, name, itext = 0, hist["github"] if "github" in hist.keys() else github, None
    hist_total = int(hist["total"]) if hist else 0
    return {
        "github": name,
        "total": base + hist_total,
        "total_now": base,
        "total_history": hist_total,
        "issues": [dict(i) for i in issues],
        "issues_text": itext,
    }


def rank_of(conn, github):
    """返回 (名次, 总人数)；不在榜则 (0, n)。口径与总榜一致（含历史补录）。"""
    rows = all_totals(conn)
    cf = github.strip().lower()
    for idx, r in enumerate(rows, 1):
        if r["github"].lower() == cf:
            return idx, len(rows)
    return 0, len(rows)


def _merged_totals(conn):
    """contrib_total（当前贡献表）＋ contrib_history（手动补录的历史）按人合并。

    历史分是**累加**的：11 号拿过的分，不该因为 12 号换了表就消失。
    """
    acc = {}
    for r in conn.execute("SELECT github,total FROM contrib_total"):
        k = r["github"].strip()
        acc[k.lower()] = acc.get(k.lower(), 0) + int(r["total"] or 0)
    for r in conn.execute("SELECT github,total FROM contrib_history"):
        k = r["github"].strip()
        acc[k.lower()] = acc.get(k.lower(), 0) + int(r["total"] or 0)
    # 还原显示名（优先当前表的写法，其次历史表）
    names = {}
    for r in conn.execute("SELECT github FROM contrib_history"):
        names.setdefault(r["github"].strip().lower(), r["github"].strip())
    for r in conn.execute("SELECT github FROM contrib_total"):
        names[r["github"].strip().lower()] = r["github"].strip()
    return [{"github": names.get(k, k), "total": v} for k, v in acc.items()]


def all_totals(conn):
    """总榜：当前表 + 历史补录，按分降序。**不限人数**（有多少人出多少人）。"""
    rows = _merged_totals(conn)
    rows.sort(key=lambda x: (-x["total"], x["github"].lower()))
    return rows


def _daily_deltas(conn):
    """逐日增量：{日期: {github小写: 增量}}。

    与 heatmap() **同一套规则**（首版/换来源 => 按自身累计作基线，否则求差），
    保证日榜/月榜与热力图格子**逐格一致**，不会两处口径打架。
    """
    snaps = conn.execute(
        "SELECT snap_date,total,COALESCE(src,'ledger') AS src,github "
        "FROM contrib_snapshot ORDER BY snap_date ASC, github ASC"
    ).fetchall()
    by_day = {}
    for s in snaps:
        by_day.setdefault(s["snap_date"], []).append(
            (s["github"].strip().lower(), s["github"], int(s["total"]), s["src"] or "ledger"))
    out, prev, prev_src = {}, {}, None
    for day in sorted(by_day):
        cur = {k: v for k, _n, v, _s in by_day[day]}
        src_today = by_day[day][0][3] if by_day[day] else "ledger"
        switch = (prev_src is not None and src_today != prev_src)
        day_map = {}
        for k, name, v, _s in by_day[day]:
            if not prev or switch:
                day_map[k] = v          # 首版 / 换口径：按自身累计作基线
            else:
                day_map[k] = v - prev.get(k, 0)
        out[day] = day_map
        prev, prev_src = cur, src_today
    return out


def board_by_day(conn, day):
    """日榜：某一天各人获得的声誉分（当天增量），降序。**只列当天有分的人**。"""
    out = [{"github": _name_of(conn, k), "total": v}
           for k, v in _daily_deltas(conn).get(day, {}).items()]
    out = [r for r in out if r["total"] != 0]
    out.sort(key=lambda x: (-x["total"], x["github"].lower()))
    return out


def board_by_month(conn, year_month):
    """月榜：某月各人获得的声誉分（= 该月各日增量之和，与热力图同源），降序。

    只列该月**有分**的人（0 分不入榜）。
    """
    acc, names = {}, {}
    for day, dm in _daily_deltas(conn).items():
        if not day.startswith(year_month):
            continue
        for k, v in dm.items():
            acc[k] = acc.get(k, 0) + v
            names[k] = _name_of(conn, k)
    out = [{"github": names[k], "total": v} for k, v in acc.items() if v != 0]
    out.sort(key=lambda x: (-x["total"], x["github"].lower()))
    return out


def _name_of(conn, key):
    """小写登录名 -> 显示名（优先当前表写法）。"""
    r = conn.execute("SELECT github FROM contrib_total WHERE lower(github)=? LIMIT 1",
                     (key,)).fetchone()
    if r:
        return r["github"]
    r = conn.execute("SELECT github FROM contrib_snapshot WHERE lower(github)=? "
                     "ORDER BY snap_date DESC LIMIT 1", (key,)).fetchone()
    return r["github"] if r else key


def snapshot_days(conn):
    """已记录的结算日列表（升序）。"""
    return [r["snap_date"] for r in conn.execute(
        "SELECT DISTINCT snap_date FROM contrib_snapshot ORDER BY snap_date")]


def add_history(conn, github, total, src="", note=""):
    """写/覆盖一条历史补录（幂等）。"""
    with _LOCK, conn:
        conn.execute(
            "INSERT INTO contrib_history(github,total,src,note,added_at)"
            " VALUES(?,?,?,?,?) ON CONFLICT(github) DO UPDATE SET"
            " total=excluded.total, src=excluded.src, note=excluded.note,"
            " added_at=excluded.added_at",
            (str(github).strip(), int(total), src, note, now_iso()),
        )


def history_all(conn):
    return [dict(r) for r in conn.execute(
        "SELECT github,total,src,note FROM contrib_history ORDER BY total DESC, github")]


# ---------------------------------------------------------------- 热力图

#: 热力图默认窗口（天）——用户要求「一个月」
HEATMAP_DAYS = 30


def heatmap(conn, github, days=HEATMAP_DAYS, first_day_counts=True, **kwargs):
    """悬赏热力图：最近 days 天每天获得的声誉分（默认一个月）。

    ★ 口径 = **今天累计 − 昨天累计**（相邻两版快照求差）：
      * 快照里存的 `total` 是该日**累计**分，格子值 = 与前一版的差；
      * 首版无前序 => 首日按自身累计展示（否则新建的库一片空白）；
      * **跨来源**（v0.1 老表 -> 新贡献表）两套算法不可比，不相减，
        该日整份记为新基线（避免 95-62=33 这种假增量）；
      * 无记录的日子记 0 并标 has=False；历史快照永不删除。
    """
    cf = github.strip().lower()
    end = date.today()
    start = end - timedelta(days=max(1, int(days)) - 1)

    snaps = conn.execute(
        "SELECT snap_date,total,COALESCE(src,'ledger') AS src FROM contrib_snapshot "
        "WHERE lower(github)=? ORDER BY snap_date ASC",
        (cf,),
    ).fetchall()
    if not snaps:
        return {"start": start.isoformat(), "end": end.isoformat(),
                "days": [], "cells": [], "max": 0, "total": 0, "baseline": None,
                "has_history": False, "weeks": 0}

    daily, srcs = {}, {}
    prev, prev_src = None, None
    baseline = None
    for s in snaps:
        d = s["snap_date"]
        cur = int(s["total"])
        cur_src = s["src"] or "ledger"
        srcs[d] = cur_src
        if prev is None or cur_src != prev_src:
            # 首版 / 换口径：不作差，按自身累计作基线
            daily[d] = cur if first_day_counts else 0
            baseline = {"date": d, "total": cur, "initial": True}
        else:
            daily[d] = cur - prev              # ★ 今天累计 − 昨天累计
        prev, prev_src = cur, cur_src

    out_days = []
    d = start
    while d <= end:
        k = d.isoformat()
        if k in daily:
            out_days.append({"date": k, "value": daily[k], "has": True,
                             "src": srcs.get(k)})
        else:
            out_days.append({"date": k, "value": 0, "has": False})
        d += timedelta(days=1)

    # 补到整周：起始日前面按周一对齐补空格，末尾补齐到周日。
    # 这样前端按 7 行（周一~周日）× N 列（周）排，格子才是小方块；
    # 不补的话 30 天铺成 5 列会变成巨大的方块（实测出过）。
    lead = start.weekday()                 # 周一=0
    cells = [None] * lead + [
        {"date": x["date"], "value": x["value"], "has": x["has"], "src": x.get("src")}
        for x in out_days
    ]
    while len(cells) % 7:
        cells.append(None)

    vals = [x["value"] for x in out_days]
    tracked = sum(1 for s in snaps if s["snap_date"] >= start.isoformat())
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": out_days,
        # 给前端的周对齐网格（None = 空格子）
        "cells": cells,
        "max": max(vals) if vals else 0,
        "total": sum(vals),
        "baseline": baseline,
        "has_history": tracked > 1,
        "weeks": max(1, len(cells) // 7),
    }


# ---------------------------------------------------------------- 悬赏

def replace_bounties(conn, items) -> int:
    """整表替换悬赏。items 来自 sync.issue_to_bounty()。"""
    ts = now_iso()
    rows, seen = [], set()
    for idx, b in enumerate(items, 1):
        bid = str(b.get("bid") or b.get("no") or idx)
        if bid in seen:                 # 同一 id 重复出现只留一条（PRIMARY KEY 冲突会炸）
            continue
        seen.add(bid)
        labels = b.get("labels")
        if isinstance(labels, (list, tuple)):
            labels = ",".join(str(x) for x in labels)
        rows.append(
            (bid, str(b.get("no") or ""), str(b.get("title") or ""), b.get("difficulty"),
             b.get("reward"), b.get("status"), b.get("deadline"), b.get("url"),
             b.get("note"), labels, b.get("updated_at"),
             (b.get("owner") or None), idx, ts)
        )
    with _LOCK, conn:
        conn.execute("DELETE FROM bounty")
        conn.executemany(
            "INSERT OR REPLACE INTO bounty"
            "(bid,no,title,difficulty,reward,status,deadline,url,note,labels,"
            " updated_at,owner,ord,synced_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def list_bounties(conn):
    """按难度降序、同难度按真源次序。

    ⚠ no 现在是稳定短 id（如 eval-site），不能 CAST 成整数——改用 ord 列。
    """
    order = ("CASE difficulty WHEN 'expert' THEN 4 WHEN 'hard' THEN 3 "
             "WHEN 'medium' THEN 2 WHEN 'easy' THEN 1 ELSE 0 END DESC")
    return [dict(r) for r in conn.execute(
        "SELECT * FROM bounty ORDER BY " + order + ", ord, no")]


# ---------------------------------------------------------------- meta

def meta_get(conn, k):
    r = conn.execute("SELECT v FROM sync_meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else None


def meta_set(conn, k, v) -> None:
    with _LOCK, conn:
        conn.execute(
            "INSERT INTO sync_meta(k,v,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at",
            (k, str(v), now_iso()),
        )
