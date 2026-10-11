# -*- coding: utf-8 -*-
"""test_build_site —— 悬赏站生成器守卫（断言 ＋ 定点变异自证）。

对象：`scripts/build_site.py`（静态站生成器——**纯函数 + 写盘**，零网络、纯 stdlib）。
真源：账本 `docs/bounty/ledger.json`；计分口径真源 `scripts/bounty_board.py`。
规则文档：`docs/bounty/README.md`；设计稿：`docs/spec/悬赏板设计_v0.1.md`。

为什么另立本件：网站面是**新仓相对旧落点的增量**，它的成立前提是
「**页面上的每个数字都能在账本里找到对应事件**」——这是**映射规则**，不是渲染细节。
故本件 = ①逐条正反断言（账本 → 榜面／悬赏板的每条映射）＋ ②每条映射一个**定点变异**
（把该映射短路 ⇒ 对应断言**必然转红**且**恰好**转红，多红=断言语义纠缠、少红=判据空转）。

断言组：
  [J] 映射面：转义 / 开放态过滤 / 难度序 / 分数降序 / 分数＝delta 求和 / 待裁标注
  [K] 落盘面：四页齐、逐字节确定、空账本不崩、注入被转义（真跑子进程）

用法：
  python -X utf8 tests/test_build_site.py            # 正向：全断言
  python -X utf8 tests/test_build_site.py --mutate   # 定点变异自证（逐条必红）
  python -X utf8 tests/test_build_site.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中期望红项；1 = 有断言失败 / 变异未按预期转红；
        2 = ANCHOR-MISS（变异锚点在实现里命中次数 ≠1——实现漂移即硬失败）。
"""
from __future__ import annotations

import inspect
import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))          # <仓根>/tests
REPO = os.path.dirname(HERE)                               # <仓根>
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import bounty_board as bb                                            # noqa: E402
import build_site as bs                                              # noqa: E402

IMPL = os.path.join(SCRIPTS, "build_site.py")

PASS = 0
FAIL = 0
FAILS = []

#: 注入夹具：出现在**会被页面渲染**的字段（登录名）上——用来证转义是活的。
INJECT_LOGIN = 'eve<img src=x onerror=alert(1)>'


def ok(name, cond, detail=""):
    """逐条记账：`[PASS]` / `[FAIL] name · detail`（同仓 scripts/test_*.py 体例）。"""
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


# 生效条件：无必需形参时返回一个可覆盖各映射面的账本夹具（结算 / 拒绝 / 超时 / 交付 / 释放 / 争议；含一条注入文本）。
def fixture_events():
    def ev(**kw):
        base = {"ts": "2026-10-09T00:00:00Z", "issue": 1, "action": "settle",
                "actor": "m", "from": "verified", "to": "settled", "holder": "",
                "difficulty": "medium", "delta": 0, "reason": ""}
        base.update(kw)
        base["id"] = bb.event_id(base)
        return base
    return [
        ev(issue=101, action="settle", actor="FuRongJun-1999", holder="alice",
           difficulty="medium", delta=3, reason="验收通过并结算"),
        ev(issue=102, action="settle", actor="FuRongJun-1999", holder="alice",
           difficulty="expert", delta=10, reason="hard 活"),
        ev(issue=103, action="expire", actor="schedule", holder="carol",
           difficulty="easy", delta=-1, reason="超时未交付，自动回板"),
        ev(issue=104, action="reject", actor="bob", holder="alice", to="claimed",
           difficulty="hard", delta=0, reason="<script>alert(1)</script>"),
        ev(issue=107, action="reject", actor=INJECT_LOGIN, holder="alice",
           to="claimed", difficulty="easy", delta=0, reason="被拒命令（注入面）"),
        ev(issue=105, action="withdraw", actor="dave", holder=None, to="open",
           difficulty="hard", delta=0, reason="主动释放"),
        ev(issue=106, action="deliver", actor="erin", holder="erin",
           to="delivered", difficulty="easy", delta=0, reason="第 1 轮交付"),
    ]


# ================================================================ [J] 映射面

def group_mapping():
    print("[J] 映射面（转义 / 开放态 / 难度序 / 分数降序 / 求和 / 待裁标注）")
    evs = fixture_events()

    ok("J1 HTML 转义：账本文本里的标签被转义（不注入页面）",
       bs.esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;",
       bs.esc("<script>"))
    ok("J2 转义覆盖引号（防属性逃逸）",
       bs.esc('" onload="x') == "&quot; onload=&quot;x", bs.esc('" onload="x'))

    rows = bs.leaderboard(evs)
    ok("J3 榜面分数降序：alice(+13) 在 carol(−1) 之前",
       rows[0]["login"] == "alice" and rows[0]["score"] == 13
       and rows[-1]["login"] == "carol" and rows[-1]["score"] == -1,
       [(r["login"], r["score"]) for r in rows])
    ok("J4 分数＝账本 delta 求和（alice = 3+10，不手写）",
       next(r for r in rows if r["login"] == "alice")["score"]
       == sum(e["delta"] for e in evs if e.get("holder") == "alice"),
       [(r["login"], r["score"]) for r in rows])
    ok("J5 被拒命令记在尝试者头上（bob 计 1 次被拒、0 分；不记持有者 alice）",
       next(r for r in rows if r["login"] == "bob")["rejects"] == 1
       and next(r for r in rows if r["login"] == "alice")["rejects"] == 0,
       [(r["login"], r["rejects"]) for r in rows])

    tasks = bs.open_tasks(evs)
    ok("J6 悬赏板只列可认领态：仅 withdraw 后的 #105 在板（settled/delivered/claimed 不在）",
       [t["number"] for t in tasks] == ["105"],
       [(t["number"], t["state"]) for t in tasks])

    mixed = bs.open_tasks([], tasks=[
        {"number": 3, "state": "open", "difficulty": "hard"},
        {"number": 1, "state": "open", "difficulty": "easy"},
        {"number": 2, "state": "open", "difficulty": "expert"},
        {"number": 4, "state": "bounty:open", "difficulty": "medium"},
    ])
    ok("J7 悬赏板按难度序升序（easy→medium→hard→expert）",
       [t["number"] for t in mixed] == ["1", "4", "3", "2"],
       [(t["number"], t["difficulty"]) for t in mixed])
    ok("J8 态标签前缀被归一（`bounty:open` 与 `open` 同判）",
       any(t["number"] == "4" for t in mixed),
       [(t["number"], t["state"]) for t in mixed])

    html_text = bs.render_honor(evs)
    ok("J9 荣誉榜页含账本算出的分数与贡献者（@alice 与 13）",
       "@alice" in html_text and ">13<" in html_text, "")
    ok("J10 荣誉榜页带计分口径标注（v1.0 质量化，已裁定）",
       "计分口径已定" in html_text, "")
    ok("J11 规则页带计分口径标注且人审闸未被写成自动通过",
       "计分口径已定" in bs.render_rules()
       and "不是自动通过" in bs.render_rules(), "")
    ok("J12 账本注入文本（登录名）进页面后被转义：原始标签不出现、转义形态出现",
       INJECT_LOGIN not in html_text
       and "&lt;img src=x onerror=alert(1)&gt;" in html_text,
       html_text[html_text.find("eve"):html_text.find("eve") + 60])

    empty = bs.render_honor([])
    ok("J13 空账本 → 荣誉榜给「暂无入账」形态且不崩",
       "暂无入账" in empty and "&lt;" not in empty.split("<main>")[1][:200],
       "")
    ok("J14 空账本 → 悬赏板给「没有可认领」形态",
       "没有可认领" in bs.render_board([]), "")

    ok("J15 计分口径复用状态机（榜面分数真源＝bounty_board.score_board：逐人分数一致）",
       {r["login"]: r["score"] for r in bs.leaderboard(evs)}
       == {r["login"]: r["score"] for r in bb.score_board(evs).values()},
       {r["login"]: r["score"] for r in bs.leaderboard(evs)})


# ================================================================ [K] 落盘面

# 生效条件：argv 为命令行参数列表时以子进程真跑生成器（cwd=仓根、UTF-8、超时 300s），返回 CompletedProcess。
def run_impl(*argv):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-X", "utf8", IMPL, *argv],
                          cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=300)


def group_build(tmp):
    print("[K] 落盘面（四页齐 / 逐字节确定 / 空账本 / 注入转义——真跑子进程）")
    ledger = os.path.join(tmp, "ledger.json")
    bb.write_ledger(ledger, fixture_events())
    out1 = os.path.join(tmp, "s1")
    out2 = os.path.join(tmp, "s2")
    r1 = run_impl("--ledger", ledger, "--out", out1)
    r2 = run_impl("--ledger", ledger, "--out", out2)
    ok("K1 生成器退出码 0（账本 → 四页落盘）", r1.returncode == 0,
       (r1.returncode, (r1.stderr or "")[-200:]))
    names = sorted(os.listdir(out1)) if os.path.isdir(out1) else []
    ok("K2 四页齐：index / board / honor / rules",
       names == ["board.html", "honor.html", "index.html", "rules.html"], names)
    same = all(io.open(os.path.join(out1, n), encoding="utf-8").read()
               == io.open(os.path.join(out2, n), encoding="utf-8").read()
               for n in names) if names else False
    ok("K3 确定性：同账本两次生成逐字节相同（不含生成时刻）", same, "")
    txt = io.open(os.path.join(out1, "honor.html"), encoding="utf-8").read() if names else ""
    ok("K4 落盘的荣誉榜含账本算出的分数（@alice 13）",
       "@alice" in txt and ">13<" in txt, txt[:120].replace("\n", " "))
    ok("K5 落盘的荣誉榜不含未转义的注入文本",
       "<script>alert(1)</script>" not in txt, "")

    empty_ledger = os.path.join(tmp, "empty.json")
    bb.write_ledger(empty_ledger, [])
    out3 = os.path.join(tmp, "s3")
    r3 = run_impl("--ledger", empty_ledger, "--out", out3)
    ok("K6 空账本 → 退出码 0 且四页仍齐（不崩）",
       r3.returncode == 0 and len(os.listdir(out3)) == 4,
       (r3.returncode, os.listdir(out3) if os.path.isdir(out3) else None))

    tasks = os.path.join(tmp, "tasks.json")
    with io.open(tasks, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"tasks": [{"number": 7, "title": "修个缺陷", "state": "open",
                              "difficulty": "hard"}]}, fh, ensure_ascii=False)
    out4 = os.path.join(tmp, "s4")
    r4 = run_impl("--ledger", empty_ledger, "--out", out4, "--tasks", tasks)
    btxt = io.open(os.path.join(out4, "board.html"), encoding="utf-8").read()
    ok("K7 --tasks 快照（issue 面）被悬赏板采用",
       r4.returncode == 0 and "#7" in btxt and "修个缺陷" in btxt,
       (r4.returncode, btxt[:120].replace("\n", " ")))

    r5 = run_impl("--ledger", empty_ledger, "--print")
    ok("K8 --print 只打印不落盘（退出码 0，stdout 含四页头）",
       r5.returncode == 0 and "===== honor.html =====" in (r5.stdout or ""),
       (r5.returncode, (r5.stdout or "")[:80]))

    bad = os.path.join(tmp, "bad.json")
    with io.open(bad, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    r6 = run_impl("--ledger", bad, "--out", os.path.join(tmp, "s6"))
    ok("K9 坏账本 → fail-closed 退出码 2（不静默当成功）",
       r6.returncode == 2, (r6.returncode, (r6.stderr or "")[-160:]))


_GROUPS = (group_mapping,)


# 生效条件：无必需形参时清账并跑 [J] 全组（落盘子进程组由调用方另跑），返回失败项前缀集合。
def run_suite():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    for fn in _GROUPS:
        fn()
    return {n.split(" ", 1)[0] for n in FAILS}


# ================================================================ 定点变异（注入映射失效 ⇒ 必红）
# 每条变异 = 把**一条映射**短路（源码级、只改内存里 exec 的副本，不落盘），
# 期望转红的断言项**恰好**等于声明集合：多红 = 断言语义纠缠，少红 = 该映射空转。

_MUTATIONS = (
    ("N0 关榜面排序（改按登录名字母序）",
     "    return (-row[\"score\"], row[\"login\"])",
     "    return (0, row[\"login\"])  # MUT", {"J3"}),
    ("N1 关开放态过滤（settled/delivered 也进悬赏板）",
     "        if rec[\"state\"] not in CLAIMABLE:",
     "        if False:  # MUT", {"J6"}),
    ("N2 关 HTML 转义（账本文本直出）",
     "    return html.escape(str(text), quote=True)",
     "    return str(text)  # MUT", {"J1", "J2", "J12"}),
    ("N3 关计分口径标注（页面不再声明口径）",
     "    if not flag:",
     "    if True:  # MUT", {"J10", "J11"}),
    ("N4 关难度序（改按号排）",
     "    return (DIFFICULTY_ORDER.get(\"difficulty:\" + rec[\"difficulty\"], 99), rec[\"number\"])",
     "    return (0, rec[\"number\"])  # MUT", {"J7"}),
)


#: 变异 → 目标函数（锚点落在哪个函数里就变异哪个）。
_MUT_TARGETS = (("N0", "_rank_key"), ("N1", "open_tasks"), ("N2", "esc"),
                ("N3", "_note_pending"), ("N4", "_task_sort_key"))


class AnchorMiss(Exception):
    pass


# 生效条件：fn_name 为模块内函数名、old 为唯一锚点、new 为替换文本时，用 inspect.getsource 取该函数源码，就地 exec 到模块全局（运行中的实现被替换），返回复原函数；锚点命中次数 ≠1 抛 AnchorMiss。
def _mut_source(fn_name, old, new):
    orig = getattr(bs, fn_name)
    src = inspect.getsource(orig)
    if src.count(old) != 1:
        raise AnchorMiss(f"{fn_name}: 锚点命中 {src.count(old)} 次（期望 1）：{old!r}")
    exec(compile(src.replace(old, new), f"<site-{fn_name}-mut>", "exec"),
         vars(bs))

    def _restore():
        setattr(bs, fn_name, orig)
    return _restore


def _anchor_preflight():
    """锚点自检：任一锚点在当前实现里命中次数 ≠1 → ANCHOR-MISS（退出码 2）。"""
    bad = []
    for (name, _old, _new, _exp), (_mid, fn) in zip(_MUTATIONS, _MUT_TARGETS):
        src = inspect.getsource(getattr(bs, fn))
        if src.count(_old) != 1:
            bad.append((name, src.count(_old)))
    if not bad:
        return 0
    for name, n in bad:
        print(f"  ANCHOR-MISS {name}：锚点命中 {n} 次（期望 1）")
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _mutate_mode():
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：逐条短路一条映射，对应断言必须**恰好**转红\n")
    base_red = run_suite()
    print(f"\n  未变异基线：红项 {len(base_red)} "
          f"{'（应为 0）' if not base_red else sorted(base_red)}")
    bad = []
    if base_red:
        bad.append(f"基线即转红：{sorted(base_red)}")
    for (name, old, new, expect), (_mid, fn) in zip(_MUTATIONS, _MUT_TARGETS):
        restore = _mut_source(fn, old, new)
        try:
            red = run_suite()
        except Exception as exc:                                  # noqa: BLE001
            red = {f"<变异体异常:{type(exc).__name__}>"}
        finally:
            restore()
        hit = red == set(expect)
        if not hit:
            bad.append(f"{name}：红项 {sorted(red)} ≠ 期望 {sorted(expect)}")
        print(f"  {'[PASS]' if hit else '[FAIL]'} {name}：红项 {len(red)}"
              f"（期望 {len(expect)}）"
              + ("" if hit else f" 实={sorted(red)} 期={sorted(expect)}"))
    print("\n定点变异：" + ("PASS（逐条恰好命中期望红项）" if not bad
                            else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--list" in argv:
        for name, _old, _new, exp in _MUTATIONS:
            print(f"  {name:<44} expect_red={len(exp)} {sorted(exp)}")
        return 0
    if "--mutate" in argv:
        return _mutate_mode()

    print("悬赏站生成器守卫（scripts/build_site.py · 账本→页面映射断言）")
    print("=" * 74)
    for fn in _GROUPS:
        fn()
    tmp = tempfile.mkdtemp(prefix="bounty_site_guard_")
    try:
        group_build(tmp)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("=" * 74)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
        return 1
    print("ALL OK（反面证明见 --mutate）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
