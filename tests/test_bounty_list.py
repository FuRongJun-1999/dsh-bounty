# -*- coding: utf-8 -*-
"""守卫：scripts/bounty_list.py（悬赏清单生成器）——断言 ＋ 定点变异自证。

  python -X utf8 tests/test_bounty_list.py            # 断言，末行「通过 N / 失败 M」
  python -X utf8 tests/test_bounty_list.py --mutate   # 定点变异自证（每条须恰好命中期望红项）

只跑断言是单向证据（绿可能是判据空转）；注入必失败再确认断言变红并点名，才是判据真的在判。
多红＝语义纠缠，少红＝判据空转——两者都算失败。

判据解耦原则（本文件踩过的坑）：**不要把多条判据建在同一个渲染基底上**。
最初 A12/A14/A16/A20 都从「总览表」取信号，于是删掉表就一次红 5 条，失去区分度。
现在 A16 看**明细章顺序**、A12 看**明细状态行**、A21 单独管**表列状态**——各管一段。
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUIET = "--quiet" in sys.argv
# 守卫侧独立声明（不 import 被守卫对象——否则同错同绿）
STATUS_CN = {"open": "开放", "claimed": "已认领", "delivered": "已交付",
             "done": "已完成", "paused": "已暂停"}
_red = []


def ok(name, cond):
    if not cond:
        _red.append(name.split(" ")[0])
    if QUIET:
        return
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))


def sandbox(mutate_json=None):
    d = tempfile.mkdtemp(prefix="bounty_list_")
    for rel in ("scripts", "docs/bounty", "tests"):
        os.makedirs(os.path.join(d, *rel.split("/")), exist_ok=True)
    for rel in ("scripts/bounty_list.py", "scripts/bounty_board.py",
                "tests/test_bounty_list.py"):
        s = os.path.join(ROOT, *rel.split("/"))
        if os.path.isfile(s):
            shutil.copy(s, os.path.join(d, *rel.split("/")))
    doc = json.load(io.open(os.path.join(ROOT, "docs", "bounty", "悬赏.json"), encoding="utf-8"))
    if mutate_json:
        mutate_json(doc)
    io.open(os.path.join(d, "docs", "bounty", "悬赏.json"), "w",
            encoding="utf-8", newline="\n").write(json.dumps(doc, ensure_ascii=False, indent=2))
    return d


def py(d, script, *args):
    r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(d, *script.split("/"))] + list(args),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"), timeout=180)
    return r.returncode, r.stdout or "", r.stderr or ""


def measure():
    m = {}
    d = sandbox()
    try:
        rc, out, err = py(d, "scripts/bounty_list.py", "--stdout")
        m["rc"], m["out"] = rc, out
        src = json.load(io.open(os.path.join(d, "docs", "bounty", "悬赏.json"), encoding="utf-8"))
        ordered = sorted(src["items"], key=lambda i: (-i["score"], i["id"]))
        m["items"], m["na_n"], m["ordered"] = src["items"], len(src["not_applicable"]), ordered
        detail = out.split("## 三、悬赏明细")[-1].split("## 四、不适用条件")[0]
        by_head = {}
        for b in detail.split("\n### ")[1:]:
            by_head[b.split("\n")[0].strip()] = b
        acc_n, prog_n, stat_cn, pos = [], [], [], {}
        for it in ordered:
            head = "%s —— %s" % (it["title"], it["direction"])
            b = by_head.get(head, "")
            a = b.split("**验收标准**（可机械复核）")[-1].split("**参考材料**")[0]
            acc_n.append(len([x for x in a.split("\n") if x.startswith("- ")]))
            p = b.split("**进度**")[-1] if "**进度**" in b else ""
            prog_n.append(len([x for x in p.split("\n") if x.startswith("- `")]))
            s = re.search(r"- \*\*状态\*\*：(\S+)", b)
            stat_cn.append(s.group(1) if s else "")
            pos[it["id"]] = detail.find("### " + head)
        m["acc_n"], m["prog_n"], m["stat_cn"] = acc_n, prog_n, stat_cn
        m["dids"] = [i for _, i in sorted((pos[x["id"]], x["id"]) for x in ordered)]
        m["anchors"] = len(re.findall(r'<a id="[^"]+"></a>', out))
        m["acc_hdr"] = out.count("**验收标准**（可机械复核）")
        m["ref_hdr"] = out.count("**参考材料**")
        m["bnd_hdr"] = out.count("**边界与不做项**")
        m["na_hdr"] = out.count("## 四、不适用条件")
        na = out.split("## 四、不适用条件")[-1] if "## 四、不适用条件" in out else out
        m["na_items"] = len([x for x in na.split("\n") if x.startswith("- ")])
        tbl = out.split("## 一、总览")[-1].split("## 二、")[0]
        m["tbl_ids"] = re.findall(r"\(#([A-Za-z0-9_-]+)\)", tbl)
        st = []
        for l in tbl.split("\n"):
            if not (l.startswith("| ") and l.rstrip().endswith(" |")) or "---" in l or "方向 |" in l:
                continue
            cells = l.strip()[1:-1].split(" | ")
            if len(cells) >= 5:
                st.append(cells[4].strip())
        m["tbl_stat_ok"] = (all(c in STATUS_CN.values() for c in st)
                            and (not st or len(st) == len(ordered)))
        m["total_ok"] = ("总分池 **%d** 分" % sum(i["score"] for i in src["items"])) in out
        m["score_render"] = all(("%s（结算分 **%d**）" % (it["difficulty"], it["score"])) in out
                                for it in src["items"])
        rc2, out2, _ = py(d, "scripts/bounty_list.py", "--stdout")
        m["det_ok"] = (out2 == out)
        py(d, "scripts/bounty_list.py")
        rc3, _, _ = py(d, "scripts/bounty_list.py", "--check")
        with io.open(os.path.join(d, "docs", "bounty", "悬赏清单.md"), "a", encoding="utf-8") as f:
            f.write("漂移注入\n")
        rc4, _, _ = py(d, "scripts/bounty_list.py", "--check")
        m["check_ok"] = (rc3 == 0 and rc4 == 1)
        d2 = sandbox(mutate_json=lambda doc: doc["items"][0].__setitem__("score", 99))
        o2 = os.path.join(d2, "docs", "bounty", "悬赏清单.md")
        rc5, _, err5 = py(d2, "scripts/bounty_list.py")
        m["failclosed_ok"] = (rc5 == 2 and not os.path.isfile(o2) and "fail-closed" in err5)
        d3 = sandbox(mutate_json=lambda doc: doc["items"][0].__setitem__("direction", "测|评"))
        rc6, out6, _ = py(d3, "scripts/bounty_list.py", "--stdout")
        m["esc_ok"] = (rc6 == 0 and "测\\|评" in out6 and "| 测|评 |" not in out6)
        bp = os.path.join(ROOT, "scripts", "bounty_board.py")
        bt = io.open(bp, encoding="utf-8").read() if os.path.isfile(bp) else ""
        blk = bt.split("DIFFICULTY_SCORES = {")[1].split("}")[0] if "DIFFICULTY_SCORES = {" in bt else ""
        board = dict(re.findall(r'"(difficulty:[a-z]+)"\s*:\s*(\d+)', blk))
        gt = io.open(os.path.join(d, "scripts", "bounty_list.py"), encoding="utf-8").read()
        gblk = gt.split("DIFFICULTY_SCORES = {")[1].split("}")[0]
        gtab = dict(re.findall(r'"([a-z]+)":\s*(\d+)', gblk))
        m["table_ok"] = (bool(board) and len(gtab) == 4
                         and all(board.get("difficulty:" + k) == v for k, v in gtab.items()))
        return m
    finally:
        shutil.rmtree(d, ignore_errors=True)


def judge(m):
    it_n = len(m["items"])
    ok("A01 rc0 生成器退出码为 0", m["rc"] == 0)
    ok("A02 title 产物首行标题正确", m["out"].startswith("# 灵枢悬赏 · 任务清单\n"))
    ok("A03 failclosed 真源校验失败即退出码 2 且不写产物", m["failclosed_ok"])
    ok("A04 rows 总览表行数 == 悬赏条数", len(m["tbl_ids"]) == it_n)
    ok("A05 total 总分池数字正确", m["total_ok"])
    ok("A06 anchor 每条都有锚点", m["anchors"] == it_n)
    ok("A07 acc 每条都有验收标准小节", m["acc_hdr"] == it_n)
    ok("A08 refs 每条都有参考材料小节", m["ref_hdr"] == it_n)
    ok("A09 bnd 每条都有边界与不做项小节", m["bnd_hdr"] == it_n)
    ok("A10 accn 每条验收条目数 == 真源条数",
       m["acc_n"] == [len(x["acceptance"]) for x in m["ordered"]])
    ok("A11 prog 每条进度条目数 == 真源条数",
       m["prog_n"] == [len(x.get("progress") or []) for x in m["ordered"]])
    ok("A12 stat 明细章状态行为中文",
       m["stat_cn"] == [STATUS_CN[x["status"]] for x in m["ordered"]])
    ok("A13 score 难度与结算分渲染一致", m["score_render"])
    ok("A14 esc 表格竖线转义", m["esc_ok"])
    ok("A15 tbl 难度表与 bounty_board.py 一致", m["table_ok"])
    ok("A16 sort 明细章顺序按分降序", m["dids"] == [x["id"] for x in m["ordered"]])
    ok("A17 det 两次运行逐字节相同", m["det_ok"])
    ok("A18 check --check 一致时 0 / 漂移时 1", m["check_ok"])
    ok("A19 na 不适用条件章存在且条目数 == 真源", m["na_hdr"] == 1 and m["na_items"] == m["na_n"])
    ok("A20 order 总览表顺序与明细章一致", m["tbl_ids"] == m["dids"])
    ok("A21 stat-tbl 总览表状态列为中文（无英文枚举泄漏）", m["tbl_stat_ok"])
    return list(_red)


MUTATIONS = [
    ("M1", "scripts/bounty_list.py",
     'return (-it["score"], it["id"])', 'return (it["score"], it["id"])', {"A16"}),
    ("M2", "scripts/bounty_list.py",
     'if it.get("score") != DIFFICULTY_SCORES[d]:', "if False:", {"A03"}),
    ("M3", "scripts/bounty_list.py", "        return 2\n", "        return 0\n", {"A03"}),
    ("M4", "scripts/bounty_list.py",
     'return str(s).replace("|", "\\\\|")', "return str(s)", {"A14"}),
    ("M5", "scripts/bounty_list.py",
     'L.append("## 四、不适用条件（本清单在什么情况下不成立）")', 'L.append("## 四、略")', {"A19"}),
    ("M6", "scripts/bounty_list.py", 'STATUS_CN[it["status"]],', 'it["status"],', {"A21"}),
    ("M7", "scripts/bounty_list.py",
     'len(items), sum(it["score"] for it in items)))', 'len(items), len(items)))', {"A05"}),
    ("M8", "scripts/bounty_list.py", 'L.append(anchor_html(it["id"]))', 'L.append("")', {"A06"}),
    ("M9", "scripts/bounty_list.py",
     'L.append("**验收标准**（可机械复核）")', 'L.append("**略**")', {"A07", "A10"}),
    ("M10", "scripts/bounty_list.py",
     'for a in it["acceptance"]:', 'for a in it["acceptance"][:1]:', {"A10"}),
    ("M11", "scripts/bounty_list.py", "        if cur != text:", "        if False:", {"A18"}),
    ("M12", "scripts/bounty_list.py",
     'prog = sorted(it.get("progress") or [], key=lambda p: p["date"])',
     'prog = (it.get("progress") or [])[:0]', {"A11"}),
    ("M13", "scripts/bounty_list.py",
     'L.append("# 灵枢悬赏 · 任务清单")', 'L.append("# 略")', {"A02"}),
    ("M14", "scripts/bounty_list.py", "    for it in items:\n        L.append(\"| %s |",
     "    for it in []:\n        L.append(\"| %s |", {"A04", "A14", "A20"}),
    ("M15", "scripts/bounty_board.py", '"difficulty:hard": 6,', '"difficulty:hard": 7,', {"A15"}),
    ("M16", "scripts/bounty_list.py",
     'STATUS_CN.get(it["status"], it["status"])', 'it["status"]', {"A12"}),
]


def run_mutations():
    base = judge(measure())
    if base:
        print("基线就红，变异自证无意义：%s" % sorted(set(base)))
        return 1
    print("基线全绿（21 条断言）——开始定点变异自证")
    bad = []
    for mid, rel, old, new, expect in MUTATIONS:
        d = sandbox()
        try:
            p = os.path.join(d, *rel.split("/"))
            t = io.open(p, encoding="utf-8").read()
            if old not in t:
                print("  [ANCHOR-MISS] %s 锚点不匹配（fail-closed，未写入）：%s" % (mid, rel))
                return 2
            io.open(p, "w", encoding="utf-8", newline="\n").write(t.replace(old, new, 1))
            r = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(d, "tests", "test_bounty_list.py"), "--quiet"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"), timeout=300)
            red = sorted(set(re.findall(r"^RED (\S+)", r.stdout or "", re.M)))
            if set(red) == set(expect):
                print("  [PASS] %s → %s" % (mid, ",".join(red)))
            else:
                print("  [FAIL] %s 期望 %s 实得 %s" % (mid, sorted(expect), red))
                bad.append(mid)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    print()
    print("定点变异：通过 %d / 失败 %d（共 %d）" % (len(MUTATIONS) - len(bad), len(bad), len(MUTATIONS)))
    if bad:
        print("未命中：%s" % bad)
    return 0 if not bad else 1


def main():
    if "--mutate" in sys.argv:
        return run_mutations()
    red = judge(measure())
    if QUIET:
        for r in sorted(set(red)):
            print("RED %s" % r)
        return 1 if red else 0
    print()
    print("通过 %d / 失败 %d" % (21 - len(set(red)), len(set(red))))
    if red:
        print("红项：%s" % sorted(set(red)))
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())