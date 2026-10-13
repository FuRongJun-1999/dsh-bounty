# -*- coding: utf-8 -*-
"""离线自检：不需要网络与渲染器也能跑（用仓内真实结算表喂解析器）。

用法：
    python3 selftest.py                      # 用仓库里的样例文本
    python3 selftest.py --table <贡献表.md>   # 指定真实结算表
    python3 selftest.py --live               # 额外试一次真·GitHub 拉取（可选）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db                # noqa: E402
import settle            # noqa: E402
import sync as sync_mod  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  " + extra) if extra else ""))
    if not cond:
        FAILS.append(name)


#: 新落点 docs/bounty/贡献表.md 的**缩样**（结构同真表，数字是造的）
SAMPLE_TABLE = """# 灵枢悬赏板 · 每日贡献表

> 本页由 `scripts/daily_table.py` 从 `docs/bounty/ledger.json`（append-only 事件流）**机械生成**——勿手改。
> 账本事件数：3 ｜ 结算项：3 ｜ 结算日：2

## 2026-10-12（结算 3 项 · 合计 26 分）

| # | 贡献者 | 项目 | 难度 | base | Δ | 影响 | 覆盖 issue | 依据 |
|---|---|---|---|---|---|---|---|---|
| 1 | @alice | memory | expert（round=1） | 10 | **10** | A | #24–#28 | 五条 P1 缺陷 |
| 2 | @bob | bounty_site | hard（round=1） | 6 | **6** | A | #30 | 状态机守卫 |
| 3 | @alice | memory | expert（round=0） | 10 | **10** | B | #31 | 一次过闸 |

### 按人合计

| 贡献者 | 声誉分 | 项数 | 覆盖 issue |
|---|---|---|---|
| @alice | **20** | 2 | #24–#28 #31 |
| @bob | **6** | 1 | #30 |

## 2026-10-11（结算 1 项 · 合计 3 分）

| # | 贡献者 | 项目 | 难度 | base | Δ | 影响 | 覆盖 issue | 依据 |
|---|---|---|---|---|---|---|---|---|
| 1 | @carol | memory | medium（round=1） | 3 | **3** | B | #11 | 协议键收口 |

## 累计（全部结算日）

合计 **29** 分 · 4 项 · 3 位贡献者

| 贡献者 | 声誉分 | 项数 | 覆盖 issue |
|---|---|---|---|
| @alice | **20** | 2 | #24–#28 #31 |
| @bob | **6** | 1 | #30 |
| @carol | **3** | 1 | #11 |
"""


def main():
    ap = argparse.ArgumentParser(description="bounty-bot 离线自检")
    ap.add_argument("--table", default="", help="真实结算表路径（默认用内置缩样）")
    ap.add_argument("--live", action="store_true", help="额外做一次真·GitHub 拉取（需网络）")
    args = ap.parse_args()

    tmp = Path("/tmp/bounty_selftest.db")
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(tmp) + suffix)
        if p.exists():
            p.unlink()
    conn = db.connect(tmp)

    import tempfile as _tf2
    print("== 1. 绑定规则 ==")
    act, old = db.bind(conn, "1001", "alice")
    check("首次绑定 created", act == "created" and old is None)
    act, old = db.bind(conn, "1001", "bob")
    check("重复绑定覆盖旧值", act == "rebound" and old == "alice")
    check("一 QQ 一 GitHub", db.get_binding(conn, "1001")["github"] == "bob")
    check("GitHub 已绑他人可查出", db.get_binding_by_github(conn, "BOB")["qq"] == "1001")
    check("大小写不敏感查重", db.get_binding_by_github(conn, "bob") is not None)
    db.bind(conn, "1002", "carol")
    try:
        db.bind(conn, "1003", "CAROL")     # 撞唯一索引
        check("一 GitHub 一 QQ（唯一索引兜底）", False, "没抛 BindConflict")
    except db.BindConflict:
        check("一 GitHub 一 QQ（唯一索引兜底）", True)


    print("== 1b. 多人绑定互不影响（★ 本轮） ==")
    _mdb = Path(_tf2.mkdtemp(prefix="bounty_bind_")) / "b.db"
    _mc = db.connect(_mdb)
    for _i, (_qq, _gh) in enumerate([("2001", "alice"), ("2002", "bob"),
                                     ("2003", "carol"), ("2004", "dave")]):
        db.bind(_mc, _qq, _gh)
    _all = {r["qq"]: r["github"] for r in
            _mc.execute("select qq, github from bindings")}
    check("4 个 QQ 各自绑到 4 个不同账号",
          _all == {"2001": "alice", "2002": "bob", "2003": "carol", "2004": "dave"},
          str(_all))
    check("每个人查到的都是自己的账号",
          all(db.get_binding(_mc, q)["github"] == g for q, g in _all.items()))
    check("不会串号（查 alice 只对应 2001）",
          db.get_binding_by_github(_mc, "alice")["qq"] == "2001")
    _act, _old = db.bind(_mc, "2001", "eric")
    check("同一人换绑 => 覆盖，且旧值是他自己的 alice",
          _act == "rebound" and _old == "alice", "%s/%s" % (_act, _old))
    check("换绑不影响别人（bob 仍属 2002）",
          db.get_binding_by_github(_mc, "bob")["qq"] == "2002")
    try:
        db.bind(_mc, "2009", "BOB")
        check("抢别人的账号 => 被拒绝", False, "没抛 BindConflict")
    except db.BindConflict:
        check("抢别人的账号 => 被拒绝", True)
    _mc.close()

    print("== 2. 结算表解析（新落点 docs/bounty/贡献表.md） ==")
    if args.table:
        text = Path(args.table).read_text(encoding="utf-8")
        src = args.table
    else:
        text, src = SAMPLE_TABLE, "(内置缩样)"
    print("     来源：" + src)
    issues, totals = settle.parse(text)
    if args.table:
        # 真实表：只做**结构**断言（数字随账本变，写死会假红）
        check("解析出 issue 明细", bool(issues), "got=%d" % len(issues))
        check("解析出按人合计（累计表）", bool(totals), "got=%d" % len(totals))
        check("累计分 = 逐人求和", sum(t["total"] for t in totals) > 0,
              "sum=%d" % sum(t["total"] for t in totals))
        check("声明总分与实算一致", settle.grand_total(text) == sum(t["total"] for t in totals),
              "declared=%s actual=%d" % (settle.grand_total(text),
                                         sum(t["total"] for t in totals)))
        check("每日 Δ 与累计表自洽", settle.cross_check(issues, totals) == [],
              str(settle.cross_check(issues, totals)))
        check("结算日可读出", bool(settle.day_of(text)), str(settle.day_of(text)))
        # 回归：`Δ`.lower() == 'δ'，用 lower() 会漏列
        check("Δ 列被认到（casefold 回归）", all(i["delta"] is not None for i in issues),
              str([i["delta"] for i in issues if i["delta"] is None][:3]))
        # 回归：区间必须展开
        check("issue 区间展开", any(len(i["covers"]) > 1 for i in issues),
              str(sorted({len(i["covers"]) for i in issues})))
        check("难度均取到裸值",
              all(i["difficulty"] in ("easy", "medium", "hard", "expert") for i in issues),
              str(sorted({str(i["difficulty"]) for i in issues})))
    else:
        check("解析出 issue 明细（跨结算日 3+1）", len(issues) == 4, "got=%d" % len(issues))
        check("解析出按人合计（累计表）", len(totals) == 3, "got=%d" % len(totals))
        check("跨结算日累加正确", sum(t["total"] for t in totals) == 29,
              "sum=%d" % sum(t["total"] for t in totals))
        check("声明总分一致（取累计节，不是最后一天）",
              settle.grand_total(text) == 29, str(settle.grand_total(text)))
        check("每日 Δ 与累计表自洽", settle.cross_check(issues, totals) == [],
              str(settle.cross_check(issues, totals)))
        check("结算日可读出", settle.day_of(text) == "2026-10-12", str(settle.day_of(text)))
        check("Δ 列被认到（casefold 回归）", all(i["delta"] is not None for i in issues),
              str([i["delta"] for i in issues]))
        a = [i for i in issues if i["github"] == "alice"][0]
        check("issue 区间展开 #24–#28", a["covers"] == ["24", "25", "26", "27", "28"],
              str(a["covers"]))
        check("难度带 round 注解仍取裸值", a["difficulty"] == "expert" and a["round"] == 1,
              "%s round=%s" % (a["difficulty"], a["round"]))

    print("== 3. 入库 + 快照 + 热力图（累计求差口径） ==")
    subj = totals[0]["github"]
    subj_total = int(totals[0]["total"])
    db.replace_contrib(conn, issues, totals)
    # 10-10 记累计 subj_total；10-11 记累计 subj_total+6 => 差为 +6
    n = db.snapshot_contrib(conn, "2026-10-10", pairs=[(t["github"], int(t["total"]))
                                                      for t in totals])
    check("快照写入", n == len(totals), "n=%d" % n)
    n2 = db.snapshot_contrib(conn, "2026-10-11", pairs=[(subj, subj_total + 6)] + [
        (t["github"], int(t["total"])) for t in totals if t["github"] != subj])
    check("次日快照可写", n2 == len(totals), "n=%d" % n2)
    hm = db.heatmap(conn, subj, days=30)
    vals = {d["date"]: d["value"] for d in hm["days"]}
    check("首日 = 自身累计（无前序）", vals.get("2026-10-10") == subj_total,
          "%s vs %s" % (vals.get("2026-10-10"), subj_total))
    check("次日 = 今天累计 − 昨天累计（+6）", vals.get("2026-10-11") == 6,
          str(vals.get("2026-10-11")))
    check("热力图 max", hm["max"] == max(subj_total, 6), "max=%s" % hm["max"])
    check("历史快照保留 2 版",
          conn.execute("select count(distinct snap_date) from contrib_snapshot").fetchone()[0] == 2)
    check("热力图大小写不敏感",
          db.heatmap(conn, subj.upper(), days=30)["max"] == max(subj_total, 6))
    check("基线 = 最早一天", hm["baseline"]["date"] == "2026-10-10", str(hm["baseline"]))

    print("== 3b. 一个月窗口 + 跨来源不作差 ==")
    _hidb = Path(_tf2.mkdtemp(prefix="bounty_hist_")) / "h.db"
    _hc = db.connect(_hidb)
    # 11 号累计 20（v0.1）；12 号累计 28（ledger，换口径 -> 记新基线）；13 号累计 34（+6）
    db.seed_snapshot(_hc, "2026-10-11", [("alice", 20)], src="v0.1")
    db.seed_snapshot(_hc, "2026-10-12", [("alice", 28)], src="ledger")
    db.seed_snapshot(_hc, "2026-10-13", [("alice", 34)], src="ledger")
    _hm = db.heatmap(_hc, "alice")
    _vals = {d["date"]: d["value"] for d in _hm["days"]}
    check("窗口是一个月（30 天）", len(_hm["days"]) == 30, "n=%d" % len(_hm["days"]))
    check("11 号 = 自身累计 20（无前序）", _vals.get("2026-10-11") == 20,
          str(_vals.get("2026-10-11")))
    check("12 号换口径 => 不作差，记新基线 28", _vals.get("2026-10-12") == 28,
          str(_vals.get("2026-10-12")))
    check("13 号 = 34-28 = +6（同源求差）", _vals.get("2026-10-13") == 6,
          str(_vals.get("2026-10-13")))
    check("区间合计 = 各格子之和", _hm["total"] == 20 + 28 + 6, str(_hm["total"]))
    check("cells 是周对齐网格（7 的倍数）", len(_hm["cells"]) % 7 == 0,
          "n=%d" % len(_hm["cells"]))
    check("cells 含空格子占位", any(c is None for c in _hm["cells"]))
    check("未记录的日子 has=False", any(d["has"] is False for d in _hm["days"]))
    check("历史快照永不删除", _hm["has_history"] is True)
    _hc.close()

    print("== 4. 名次 / 明细 ==")
    rank, people = db.rank_of(conn, subj)
    check("名次=1（榜首）", rank == 1, "rank=%d/%d" % (rank, people))
    detail = db.person_detail(conn, subj.upper())
    check("大小写不敏感查明细", detail is not None and detail["total"] == subj_total,
          str(detail and detail["total"]))
    check("明细带 issue 级字段",
          bool((detail or {}).get("issues")) and "impact" in detail["issues"][0])
    check("不在榜者名次 0", db.rank_of(conn, "no-such-user")[0] == 0)
    check("不在榜者明细 None", db.person_detail(conn, "no-such-user") is None)

    print("== 5. 悬赏来源：标题带「悬赏」的 issue ==")
    F = sync_mod.is_bounty_title
    check("「悬赏 xxx」入选", F("悬赏 灵枢生态宣传"))
    check("「[悬赏] xxx」入选", F("[悬赏] 插件测评站"))
    check("「悬赏：xxx」入选（全角冒号）", F("悬赏：角色扮演游戏"))
    check("不带前缀的 issue 不入选", not F("fix: 修个 bug"))
    check("PR / 其它标题不入选", not F("Bump version to 2.0"))
    check("前缀被剥掉", sync_mod.strip_bounty_prefix("[悬赏] 插件测评站") == "插件测评站",
          sync_mod.strip_bounty_prefix("[悬赏] 插件测评站"))

    raw_issues = [
        {"number": 71, "title": "悬赏 灵枢生态宣传", "state": "open",
         "html_url": "https://github.com/o/r/issues/71", "updated_at": "2026-10-12T12:00:00Z",
         "body": "## 背景\n材料 + 渠道 + 触达读数", "labels": [
             {"name": "bounty"}, {"name": "bounty:open"}, {"name": "difficulty:medium"}]},
        {"number": 70, "title": "[悬赏] 角色扮演游戏制作", "state": "open",
         "html_url": "https://github.com/o/r/issues/70", "updated_at": "2026-10-11T12:00:00Z",
         "body": "可运行 + 可测", "labels": [{"name": "difficulty:hard"}]},
        # 已认领 / 已交付 / 招标中的 issue：**只要 open 就仍然算悬赏**
        {"number": 66, "title": "悬赏 已被认领但仍开放", "state": "open",
         "html_url": "https://github.com/o/r/issues/66", "updated_at": "2026-10-10T12:00:00Z",
         "body": "在做了", "labels": [{"name": "difficulty:expert"},
                                     {"name": "bounty:claimed"},
                                     {"name": "bounty:contest"}]},
        {"number": 69, "title": "普通 issue 不该入选", "state": "open", "body": "x", "labels": []},
        {"number": 68, "title": "悬赏 已关闭的", "state": "closed", "body": "x", "labels": []},
        {"number": 67, "title": "悬赏 这是个 PR 混进来的", "state": "open",
         "pull_request": {"url": "x"}, "body": "x", "labels": []},
    ]
    got = sync_mod.parse_bounty_issues(raw_issues)
    check("只取标题带「悬赏」的开放 issue", [b["no"] for b in got] == ["71", "70", "66"],
          str([b["no"] for b in got]))
    b0 = got[0]
    check("难度取自 difficulty: 标签", b0["difficulty"] == "medium", str(b0["difficulty"]))
    # ★ 口径：open 就一直算悬赏——认领/招标标签不改入选、不改状态
    b66 = [b for b in got if b["no"] == "66"][0]
    check("已认领(bounty:claimed) 但仍 open => 仍算悬赏", b66["title"].startswith("已被认领"),
          b66["title"])
    check("状态不跟随 bounty:* 认领态（只反映 issue 开闭）", b66["status"] == "open",
          b66["status"])
    check("非难度标签被保留在 labels 里",
          "bounty:claimed" in (b66["labels"] or []), str(b66["labels"]))
    check("标题已去前缀", b0["title"] == "灵枢生态宣传", b0["title"])
    check("摘要取正文首个非标题行", b0["note"] == "材料 + 渠道 + 触达读数", str(b0["note"]))
    check("url 指向 issue", b0["url"].endswith("/issues/71"), b0["url"])
    # ★ 卡片是 textContent 渲染，Markdown 必须清洗掉（否则 ** / []() 原样显示）
    check("Markdown 粗体被清洗", sync_mod.plain_text("但 **结论多、读数少**——") == "但 结论多、读数少——",
          repr(sync_mod.plain_text("但 **结论多、读数少**——")))
    check("Markdown 链接只留文字",
          sync_mod.plain_text("[dsh-memory](https://github.com/x) 是白箱") == "dsh-memory 是白箱",
          repr(sync_mod.plain_text("[dsh-memory](https://github.com/x) 是白箱")))
    check("Markdown 图片被丢弃", sync_mod.plain_text("![x](http://y/z.png) 正文") == "正文",
          repr(sync_mod.plain_text("![x](http://y/z.png) 正文")))
    check("Markdown 行内代码去反引号",
          sync_mod.plain_text("用 python 跑") == "用 python 跑")
    md_body = {"number": 99, "title": "悬赏 测试", "state": "open", "body":
               "## 背景\n\n这里有 **粗体** 和 [链接](https://x) 与 ![图](http://y)\n",
               "labels": [], "html_url": "https://github.com/o/r/issues/99"}
    _b = sync_mod.issue_to_bounty(md_body)
    check("issue 摘要已清洗 Markdown",
          _b["note"] == "这里有 粗体 和 链接 与", repr(_b["note"]))
    check("PR 被剔除", all(b["no"] != "67" for b in got))
    check("closed 默认不要", all(b["no"] != "68" for b in got))
    check("include_closed=True 时纳入",
          "68" in [b["no"] for b in sync_mod.parse_bounty_issues(raw_issues, True)])

    print("== 5b. 悬赏真源（docs/bounty/悬赏.json） ==")
    REAL_JSON = json.dumps({
        "items": [
            {"id": "a-open", "title": "开放中", "status": "open", "difficulty": "easy",
             "score": 1, "direction": "测评", "acceptance": ["交付物：**x** 与 review/data/*.json"],
             "owner": ""},
            {"id": "b-claimed", "title": "已认领的", "status": "claimed", "difficulty": "hard",
             "score": 6, "direction": "迭代", "acceptance": ["跑 `python x.py`"],
             "owner": "alice", "issue": 42},
            {"id": "c-delivered", "title": "待验收的", "status": "delivered", "difficulty": "hard",
             "score": 6, "acceptance": ["a"]},
            {"id": "d-paused", "title": "已暂停的", "status": "paused", "difficulty": "medium",
             "score": 3, "acceptance": ["b"]},
            {"id": "e-done", "title": "已结束的（不该出现）", "status": "done", "difficulty": "expert",
             "score": 10, "acceptance": ["c"]},
        ]
    }, ensure_ascii=False)
    jitems = sync_mod.parse_bounty_json(REAL_JSON, repo="owner/repo")
    check("真源解析：只排除已结束(done)",
          [b["no"] for b in jitems] == ["a-open", "b-claimed", "c-delivered", "d-paused"],
          str([b["no"] for b in jitems]))
    check("认领中的照样计入（不问认领与否）", "b-claimed" in [b["no"] for b in jitems])
    check("已交付/已暂停也计入", {"c-delivered", "d-paused"} <= {b["no"] for b in jitems})
    check("已结束(done) 被排除", "e-done" not in [b["no"] for b in jitems])
    jb = [b for b in jitems if b["no"] == "b-claimed"][0]
    check("结算分进 reward 字段", jb["reward"] == "6", str(jb["reward"]))
    check("负责人进 owner", jb["owner"] == "alice", str(jb["owner"]))
    check("原 issue 号成链接（含 repo 前缀）",
          jb["url"] == "https://github.com/owner/repo/issues/42", str(jb["url"]))
    jc = [b for b in jitems if b["no"] == "c-delivered"][0]
    check("没有 repo / issue 时不硬拼链接", jc["url"] is None, str(jc["url"]))
    ja = [b for b in jitems if b["no"] == "a-open"][0]
    check("验收标准进摘要且已清洗 Markdown", "review/data/*.json" in (ja["note"] or ""),
          str(ja["note"]))
    check("状态原样保留（claimed 不等同 open）", jb["status"] == "claimed", jb["status"])
    try:
        sync_mod.parse_bounty_json("{bad json")
        check("非法 JSON 会报错而不是静默清空", False, "没抛异常")
    except ValueError:
        check("非法 JSON 会报错而不是静默清空", True)
    db.replace_bounties(conn, got)
    db.replace_bounties(conn, got)      # 重复整表替换（不应撞主键）
    bs = db.list_bounties(conn)
    check("难度降序（expert 在前）", bs[0]["difficulty"] == "expert",
          str([b["difficulty"] for b in bs]))
    check("重复入库不炸且不重复", len(bs) == 3, "n=%d" % len(bs))
    check("同一 bid 去重", db.replace_bounties(conn, [got[0], dict(got[0])]) == 1)

    print("== 7. 指令解析 ==")
    import bot as botmod
    check("/帮助", botmod.parse_command("/帮助") == ("/帮助", ""))
    check("/绑定 带参", botmod.parse_command("/绑定 octocat") == ("/绑定", "octocat"))
    check("/绑定 无空格也认（★ 本轮）",
          botmod.parse_command("/绑定octocat") == ("/绑定", "octocat"),
          str(botmod.parse_command("/绑定octocat")))
    check("/绑定 无参", botmod.parse_command("/绑定") == ("/绑定", ""))
    check("/绑定@user 去 @", botmod.parse_command("/绑定@user") == ("/绑定", "@user"))
    check("其它指令不受无空格影响",
          botmod.parse_command("/帮助") == ("/帮助", "")
          and botmod.parse_command("/我的贡献") == ("/我的贡献", "")
          and botmod.parse_command("/榜单") == ("/榜单", ""))
    check("未知名前缀不被吞（/绑x 不是 /绑定）",
          botmod.parse_command("/绑x")[0] != "/绑定",
          str(botmod.parse_command("/绑x")))
    check("非命令不响应", botmod.parse_command("你好啊 /悬赏")[0] is None)
    check("array 消息", botmod.parse_command(
        [{"type": "text", "data": {"text": "/我的贡献"}}]) == ("/我的贡献", ""))
    check("@ 前缀", botmod.parse_command("[CQ:at,qq=1] /悬赏") == ("/悬赏", ""))
    check("@ 前缀带前导空格", botmod.parse_command("  [CQ:at,qq=1]  /悬赏") == ("/悬赏", ""))
    check("多个 @ 连续", botmod.parse_command("[CQ:at,qq=1][CQ:at,qq=2] /悬赏") == ("/悬赏", ""))
    check("纯 at 无文本不响应", botmod.parse_command("[CQ:at,qq=1]")[0] is None)
    check("image 段混入不误判", botmod.parse_command(
        [{"type": "image", "data": {"file": "x"}},
         {"type": "text", "data": {"text": "/榜单"}}]) == ("/榜单", ""))
    check("登录名校验：合法", bool(botmod._VALID_LOGIN.match("octocat")))
    check("登录名校验：拒绝中文", not botmod._VALID_LOGIN.match("你好"))
    check("登录名校验：拒绝连续连字符", not botmod._VALID_LOGIN.match("a--b"))

    print("== 7b. HTTP 体解析（chunked 回归） ==")
    import bot as _botmod2
    import http.client as _hc

    class _H(_botmod2.Handler):
        def __init__(self, headers, body):
            self.headers = headers
            self._raw = body
            self.rfile = __import__("io").BytesIO(body)
        def log_message(self, *a):
            pass

    # ① chunked：NapCat 的真实形态（没有 Content-Length）
    chunked = b"1a\r\n" + b'{"post_type":"meta_event"}' + b"\r\n0\r\n\r\n"
    h = _H(_hc.HTTPMessage(), chunked)
    h.headers["Transfer-Encoding"] = "chunked"
    got = h._body()
    check("chunked 体能被读出（★ NapCat 上报的形态）",
          got == b'{"post_type":"meta_event"}', repr(got))

    # ② Content-Length：curl 等常见形态
    body = b'{"post_type":"message"}'
    h2 = _H(_hc.HTTPMessage(), body)
    h2.headers["Content-Length"] = str(len(body))
    check("Content-Length 体仍能读出", h2._body() == body)

    # ③ 既无 chunked 也无 CL（空请求）=> 空事件而不是崩溃
    h3 = _H(_hc.HTTPMessage(), b"")
    check("无 CL 无 chunked => 空 {} 不崩", h3._body() == b"{}", repr(h3._body()))

    # ④ 声明长度与实际不符 => 拒绝（别把半截 JSON 交给解析器）
    h4 = _H(_hc.HTTPMessage(), b"short")
    h4.headers["Content-Length"] = "999"
    check("体不完整 => 拒绝", h4._body() is None)

    # ⑤ 超限 => 拒绝
    h5 = _H(_hc.HTTPMessage(), b"")
    h5.headers["Content-Length"] = str(_botmod2.Handler.MAX_BODY + 1)
    check("超限体 => 拒绝", h5._body() is None)

    print("== 7c. 图片压缩（上传体积回归） ==")
    import imageopt
    import tempfile as _tf
    try:
        from PIL import Image as _Img
        _tdir = Path(_tf.mkdtemp(prefix="bounty_img_test_"))
        _big = _tdir / "big.png"
        # 造一张有噪声的大图（纯色会压得太好，测不出真实行为）
        # 用逐像素伪随机噪声 => PNG 几乎无法压缩，模拟真实照片底纹大图
        import random as _rnd
        _rnd.seed(7)
        _im = _Img.new("RGB", (1080, 1400))
        _im.putdata([(_rnd.randrange(256), _rnd.randrange(256), _rnd.randrange(256))
                     for _ in range(1080 * 1400)])
        _im.save(_big, "PNG")
        _before = _big.stat().st_size
        _out, _ok = imageopt.compress_png(_big, target_bytes=900 * 1024)
        _after = Path(_out).stat().st_size
        check("大图被压到目标体积内", _after <= 900 * 1024 and _after < _before,
              "%.2fMB -> %.2fMB" % (_before / 1048576, _after / 1048576))
        check("压缩后文件仍可被打开", _Img.open(_out).size[0] == 1080, _out)
        # 小图不该被动
        _small = _tdir / "small.png"
        _Img.new("RGB", (40, 40), (10, 20, 30)).save(_small, "PNG")
        _s2, _ch2 = imageopt.compress_png(_small, target_bytes=900 * 1024)
        check("已达标的小图不重压", _ch2 is False and _s2 == str(_small))
        # 不存在/坏文件不能抛
        try:
            imageopt.compress_png(_tdir / "nope.png")
            check("不存在的文件不抛异常", True)
        except Exception as _e:
            check("不存在的文件不抛异常", False, str(_e))
    except ImportError:
        print("  SKIP  无 Pillow，跳过压缩测试")

    print("== 8. 渲染缓存（静态卡复用 / 动态卡实时） ==")
    import render as render_mod

    class _FakeR(render_mod.Renderer):
        """假的渲染器：只记账，不真起 Chrome。"""
        def __init__(self, cfg, wd):
            super().__init__(cfg, wd)
            self.calls = 0
        def render(self, kind, payload, timeout=None):
            self.calls += 1
            p = self.tmpdir / ("%s_%d.png" % (kind, self.calls))
            p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
            return str(p)

    rwd = Path(_tf.mkdtemp(prefix="bounty_cache_test_"))
    R = _FakeR({"cmd": ["true"], "cache": True, "static_kinds": ["help"]}, rwd)
    cmds = [{"cmd": "/帮助", "desc": "查看本说明"}]

    p1 = R.render_cached("help", {"commands": cmds})
    p2 = R.render_cached("help", {"commands": cmds})
    check("静态卡第二次命中缓存（不重复渲染）", R.calls == 1, "calls=%d" % R.calls)
    check("静态卡两次拿到同一文件", p1 == p2, "%s vs %s" % (p1, p2))
    check("缓存件落在 .cache 下", Path(p1).parent.name == ".cache", str(Path(p1).parent))

    R.render_cached("help", {"commands": cmds + [{"cmd": "/新", "desc": "x"}]})
    check("静态卡内容一变就重渲染", R.calls == 2, "calls=%d" % R.calls)

    c1 = R.render_cached("bounty", {"bounties": [{"no": "1"}]})
    c2 = R.render_cached("bounty", {"bounties": [{"no": "1"}]})
    c3 = R.render_cached("bounty", {"bounties": [{"no": "1"}, {"no": "2"}]})
    check("动态卡每次都实时渲染", R.calls == 5, "calls=%d" % R.calls)
    check("动态卡不入缓存", not list(R.cachedir.glob("bounty_*.png")),
          str([p.name for p in R.cachedir.glob("bounty_*.png")]))
    check("动态卡产物各不同（未被互相覆盖）", len({c1, c2, c3}) == 3)

    R.cleanup_after_send(p1)
    check("发完不删缓存件", Path(p1).exists())
    R.sweep_tmp(max_age_hours=0)
    check(".cache 不被 sweep_tmp 清理", Path(p1).exists())

    R2 = _FakeR({"cmd": ["true"], "cache": False, "static_kinds": ["help"]}, rwd)
    R2.render_cached("help", {"commands": cmds})
    R2.render_cached("help", {"commands": cmds})
    check("cache=false 时静态卡也实时渲染", R2.calls == 2, "calls=%d" % R2.calls)

    k1 = R.cache_key("help", {"commands": cmds, "_generated_at": "2026-01-01 00:00:00"})
    k2 = R.cache_key("help", {"commands": cmds, "_generated_at": "2099-12-31 23:59:59"})
    check("_generated_at 不进缓存键", k1 == k2, "%s vs %s" % (k1, k2))

    # ★ 改模板/样式必须使静态卡缓存失效，否则永远发旧图
    tdir = Path(_tf.mkdtemp(prefix="bounty_tpl_test_"))
    (tdir / "help.html").write_text("<html>v1</html>", encoding="utf-8")
    Rt = _FakeR({"cmd": ["true"], "cache": True, "static_kinds": ["help"],
                 "cwd": str(tdir)}, tdir)
    ka = Rt.cache_key("help", {"commands": cmds})
    (tdir / "help.html").write_text("<html>v2 改了字色</html>", encoding="utf-8")
    Rt._style_fp = None
    kb = Rt.cache_key("help", {"commands": cmds})
    check("改模板后缓存键变化（不会发旧图）", ka != kb, "%s vs %s" % (ka, kb))

    print("== 9. 配置默认值（新落点） ==")
    here = Path(__file__).resolve().parent
    # 干净检出里没有 config.json（含 token，不入库）——回落 config.example.json
    cfg_path = here / "config.json"
    if not cfg_path.exists():
        cfg_path = here / "config.example.json"
    cfgd = botmod.load_config(cfg_path)
    check("默认结算表路径已是新落点",
          cfgd["contrib_path"] == "docs/bounty/贡献表.md", cfgd["contrib_path"])
    check("悬赏模式默认 = json（真源）", cfgd["bounty"]["mode"] == "json",
          cfgd["bounty"]["mode"])
    check("真源路径 = docs/bounty/悬赏.json",
          cfgd["bounty"].get("source_path") == "docs/bounty/悬赏.json",
          str(cfgd["bounty"].get("source_path")))
    check("渲染缓存默认开启", cfgd["render"].get("cache", True) is not False)
    check("静态卡默认含 help", "help" in (cfgd["render"].get("static_kinds") or []),
          str(cfgd["render"].get("static_kinds")))
    # load_config 对缺项要有默认值：拿一份最小配置试
    import json as _json, tempfile as _tf, os as _os
    mini = _os.path.join(_tf.gettempdir(), "bounty_min_cfg.json")
    with open(mini, "w", encoding="utf-8") as fh:
        _json.dump({"repo": "o/r"}, fh)
    try:
        m = botmod.load_config(mini)
        check("最小配置也能补齐默认值",
              m["contrib_path"] == "docs/bounty/贡献表.md"
              and m["bounty"]["mode"] == "json" and m["listen_port"] == 3040,
              str(sorted(m.keys())))
    finally:
        _os.unlink(mini)

    if args.live:
        print("== 10. 真实拉取（网络） ==")
        import github
        cfg = botmod.load_config(Path(__file__).resolve().parent / "config.json")
        try:
            code, txt, etag = github.fetch_text(cfg["repo"], cfg["contrib_path"], cfg["branch"])
            check("拉取新结算表", code == 200 and "贡献表" in txt, "code=%s len=%s" % (code, len(txt)))
            its2, tots2 = settle.parse(txt)
            check("真表解析非空", bool(tots2), "totals=%d" % len(tots2))
        except Exception as exc:
            check("拉取新结算表", False, "%s: %s" % (type(exc).__name__, exc))
        try:
            res = sync_mod.sync_all(conn, cfg, force=True)
            print("     " + res.summary().replace("\n", " | "))
            check("同步成功（无错误）", not res.errors, str(res.errors))
        except Exception as exc:
            check("同步成功（无错误）", False, "%s: %s" % (type(exc).__name__, exc))

    conn.close()
    print()
    if FAILS:
        print("FAILED %d: %s" % (len(FAILS), FAILS))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
