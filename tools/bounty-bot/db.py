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
CREATE TABLE IF NOT EXISTS contrib_snapshot (
    snap_date   TEXT NOT NULL,
    github      TEXT NOT NULL,
    total       INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
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
    synced_at   TEXT NOT NULL
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
    "bounty": {"labels": "TEXT", "updated_at": "TEXT"},
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


def snapshot_contrib(conn, snap_date=None) -> int:
    """把当日「按人合计」落成快照（同日重复同步覆盖当日，不改历史日）。"""
    snap_date = snap_date or today()
    ts = now_iso()
    rows = conn.execute("SELECT github, total FROM contrib_total").fetchall()
    if not rows:
        return 0
    with _LOCK, conn:
        conn.executemany(
            "INSERT INTO contrib_snapshot(snap_date,github,total,captured_at)"
            " VALUES(?,?,?,?) "
            "ON CONFLICT(snap_date,github) DO UPDATE SET total=excluded.total,"
            " captured_at=excluded.captured_at",
            [(snap_date, r["github"], int(r["total"]), ts) for r in rows],
        )
    return len(rows)


def person_detail(conn, github):
    """某个 github 账户的完整贡献明细（大小写不敏感）。"""
    cf = github.strip().lower()
    total_row = conn.execute(
        "SELECT * FROM contrib_total WHERE lower(github)=?", (cf,)
    ).fetchone()
    issues = conn.execute(
        "SELECT * FROM contrib_issue WHERE lower(github)=? ORDER BY CAST("
        "REPLACE(REPLACE(issue_no, '#', ''), ' ', '') AS INTEGER)",
        (cf,),
    ).fetchall()
    if total_row is None and not issues:
        return None
    return {
        "github": (total_row["github"] if total_row else issues[0]["github"]),
        "total": int(total_row["total"]) if total_row else sum(int(i["delta"] or 0) for i in issues),
        "issues": [dict(i) for i in issues],
        "issues_text": total_row["issues"] if total_row else None,
    }


def rank_of(conn, github):
    """返回 (名次, 总人数)；不在榜则 (0, n)。"""
    rows = conn.execute(
        "SELECT github, total FROM contrib_total ORDER BY total DESC, github ASC"
    ).fetchall()
    cf = github.strip().lower()
    for idx, r in enumerate(rows, 1):
        if r["github"].lower() == cf:
            return idx, len(rows)
    return 0, len(rows)


def all_totals(conn):
    return [dict(r) for r in conn.execute(
        "SELECT github,total FROM contrib_total ORDER BY total DESC, github ASC"
    )]


# ---------------------------------------------------------------- 热力图

def heatmap(conn, github, weeks=53):
    """悬赏热力图：每天获得的声誉分。

    口径：相邻两版快照求差 => 当日增量。首版快照无前序，记 0，并在响应里
    给出 baseline 供前端标注「初始快照」。历史快照永不删除。
    """
    cf = github.strip().lower()
    end = date.today()
    start = end - timedelta(days=weeks * 7 - 1)

    snaps = conn.execute(
        "SELECT snap_date,total FROM contrib_snapshot WHERE lower(github)=? "
        "ORDER BY snap_date ASC",
        (cf,),
    ).fetchall()
    if not snaps:
        return {"start": start.isoformat(), "end": end.isoformat(),
                "days": [], "max": 0, "total": 0, "baseline": None,
                "has_history": False}

    daily = {}
    prev = None
    baseline = None
    for s in snaps:
        d = s["snap_date"]
        cur = int(s["total"])
        if prev is None:
            daily[d] = 0
            baseline = {"date": d, "total": cur}
        else:
            daily[d] = cur - prev
        prev = cur

    days = []
    d = start
    while d <= end:
        k = d.isoformat()
        if k in daily:
            days.append({"date": k, "value": daily[k], "has": True})
        else:
            days.append({"date": k, "value": 0, "has": False})
        d += timedelta(days=1)

    vals = [x["value"] for x in days]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        "max": max(vals) if vals else 0,
        "total": sum(vals),
        "baseline": baseline,
        "has_history": len(snaps) > 1,
    }


# ---------------------------------------------------------------- 悬赏

def replace_bounties(conn, items) -> int:
    """整表替换悬赏。items 来自 sync.issue_to_bounty()。"""
    ts = now_iso()
    rows, seen = [], set()
    for idx, b in enumerate(items, 1):
        bid = str(b.get("bid") or b.get("no") or idx)
        if bid in seen:                 # 同一 issue 重复出现只留一条（PRIMARY KEY 冲突会炸）
            continue
        seen.add(bid)
        labels = b.get("labels")
        if isinstance(labels, (list, tuple)):
            labels = ",".join(str(x) for x in labels)
        rows.append(
            (bid, str(b.get("no") or ""), str(b.get("title") or ""), b.get("difficulty"),
             b.get("reward"), b.get("status"), b.get("deadline"), b.get("url"),
             b.get("note"), labels, b.get("updated_at"), ts)
        )
    with _LOCK, conn:
        conn.execute("DELETE FROM bounty")
        conn.executemany(
            "INSERT OR REPLACE INTO bounty"
            "(bid,no,title,difficulty,reward,status,deadline,url,note,labels,"
            " updated_at,synced_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def list_bounties(conn):
    order = ("CASE difficulty WHEN 'expert' THEN 4 WHEN 'hard' THEN 3 "
             "WHEN 'medium' THEN 2 WHEN 'easy' THEN 1 ELSE 0 END DESC")
    return [dict(r) for r in conn.execute(
        "SELECT * FROM bounty ORDER BY " + order + ", CAST(no AS INTEGER)")]


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
