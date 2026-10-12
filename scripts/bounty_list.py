# -*- coding: utf-8 -*-
"""灵枢悬赏 · 任务清单生成器（纯 stdlib，零第三方依赖）。

真源：docs/bounty/悬赏.json   →   产物：docs/bounty/悬赏清单.md
用法：python -X utf8 scripts/bounty_list.py            # 写产物
      python -X utf8 scripts/bounty_list.py --check     # 只校验产物是否与真源一致（CI 用，退出码 1=漂移）
      python -X utf8 scripts/bounty_list.py --stdout    # 打印不落盘
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "bounty", "悬赏.json")
OUT = os.path.join(ROOT, "docs", "bounty", "悬赏清单.md")

# 难度→结算分（**唯一权威**在本文件；守卫断言它与 bounty_board.py 一致）
DIFFICULTY_SCORES = {"easy": 1, "medium": 3, "hard": 6, "expert": 10}
STATUS_CN = {"open": "开放", "claimed": "已认领", "delivered": "已交付",
             "done": "已完成", "paused": "已暂停"}


def load(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def anchor_html(i):
    """锚点 HTML。用 chr(34) 拼引号——避开源码里的转义引号序列。"""
    return "<a id=" + chr(34) + i + chr(34) + "></a>"

def sort_key(it):
    # 分高者在前；同分按 id 升序（稳定、可复现）
    return (-it["score"], it["id"])


def esc(s):
    """表格单元格转义：竖线会破坏列结构。"""
    return str(s).replace("|", "\\|")


def render(doc):
    L = []
    items = sorted(doc["items"], key=sort_key)
    L.append("# 灵枢悬赏 · 任务清单")
    L.append("")
    L.append("> **本文件由 `scripts/bounty_list.py` 机械生成——请勿手改**（手改会在下次生成时被覆盖）。")
    L.append("> 真源：`docs/bounty/悬赏.json`；改真源后重跑 `python -X utf8 scripts/bounty_list.py`。")
    L.append("")
    L.append("更新日期：%s" % doc["updated"])
    L.append("")
    L.append(doc["intro"])
    L.append("")
    # ---- 总览表 ----
    L.append("## 一、总览")
    L.append("")
    L.append("| 方向 | 悬赏 | 难度 | 结算分 | 状态 | 负责人 |")
    L.append("| --- | --- | --- | ---: | --- | --- |")
    for it in items:
        L.append("| %s | [%s](#%s) | %s | %d | %s | %s |" % (
            esc(it["direction"]), esc(it["title"]), it["id"],
            esc(it["difficulty"]), it["score"],
            STATUS_CN[it["status"]],
            esc(it["owner"]) if it["owner"] else "**待认领**"))
    L.append("")
    L.append("合计 **%d** 条；总分池 **%d** 分。" % (
        len(items), sum(it["score"] for it in items)))
    L.append("")
    # ---- 怎么用 ----
    L.append("## 二、怎么用")
    L.append("")
    for i, line in enumerate(doc["howto"], 1):
        L.append("%d. %s" % (i, line))
    L.append("")
    # ---- 逐条 ----
    L.append("## 三、悬赏明细")
    L.append("")
    for it in items:
        L.append(anchor_html(it["id"]))
        L.append("")
        L.append("### %s —— %s" % (it["title"], it["direction"]))
        L.append("")
        L.append("- **难度**：%s（结算分 **%d**）" % (it["difficulty"], it["score"]))
        L.append("- **期望交付形态**：%s" % it["form"])
        L.append("- **状态**：%s%s" % (
            STATUS_CN.get(it["status"], it["status"]),
            ("　｜　**负责人**：@%s" % it["owner"]) if it["owner"] else "　｜　**待认领**"))
        if it.get("issue"):
            L.append("- **原 issue 留痕**：[#%d](https://github.com/FuRongJun-1999/dsh-bounty/issues/%d) —— %s" % (
                it["issue"], it["issue"], it.get("issue_note", "")))
        L.append("")
        L.append("**验收标准**（可机械复核）")
        L.append("")
        for a in it["acceptance"]:
            L.append("- %s" % a)
        L.append("")
        L.append("**参考材料**")
        L.append("")
        for r in it["refs"]:
            L.append("- %s" % r)
        L.append("")
        L.append("**边界与不做项**")
        L.append("")
        for b in it["boundary"]:
            L.append("- %s" % b)
        L.append("")
        prog = sorted(it.get("progress") or [], key=lambda p: p["date"])
        if prog:
            L.append("**进度**")
            L.append("")
            for p in prog:
                L.append("- `%s` %s" % (p["date"], p["note"]))
            L.append("")
        L.append("---")
        L.append("")
    # ---- 不适用条件 ----
    L.append("## 四、不适用条件（本清单在什么情况下不成立）")
    L.append("")
    for n in doc["not_applicable"]:
        L.append("- %s" % n)
    L.append("")
    return "\n".join(L)


def validate(doc):
    """真源自校验：错即 fail-closed（退出码 2），绝不产出半截文档。"""
    errs = []
    if not isinstance(doc.get("items"), list) or not doc["items"]:
        errs.append("items 缺失或为空")
    seen = set()
    for it in doc.get("items", []):
        i = it.get("id", "?")
        for k in ("id", "title", "direction", "difficulty", "score", "form",
                  "status", "acceptance", "refs", "boundary"):
            if k not in it:
                errs.append("%s 缺字段 %s" % (i, k))
        if i in seen:
            errs.append("id 重复：%s" % i)
        seen.add(i)
        d = it.get("difficulty")
        if d not in DIFFICULTY_SCORES:
            errs.append("%s 难度非法：%r" % (i, d))
        elif it.get("score") != DIFFICULTY_SCORES[d]:
            errs.append("%s 分与难度不符：%s→%d 表值 %d"
                        % (i, d, it.get("score"), DIFFICULTY_SCORES[d]))
        if not it.get("acceptance"):
            errs.append("%s 验收标准为空" % i)
        if it.get("status") not in STATUS_CN:
            errs.append("%s 状态非法：%r" % (i, it.get("status")))
    return errs


def main(argv):
    doc = load(SRC)
    errs = validate(doc)
    if errs:
        sys.stderr.write("真源校验失败（fail-closed，未写任何产物）：\n")
        for e in errs:
            sys.stderr.write("  - %s\n" % e)
        return 2
    text = render(doc)
    if "--stdout" in argv:
        sys.stdout.write(text)
        return 0
    if "--check" in argv:
        cur = ""
        if os.path.isfile(OUT):
            with io.open(OUT, encoding="utf-8") as f:
                cur = f.read()
        if cur != text:
            sys.stderr.write("产物与真源漂移：%s\n" % OUT)
            return 1
        print("产物与真源一致：%s" % OUT)
        return 0
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("已生成 %s（%d 条悬赏，总分池 %d）"
          % (OUT, len(doc["items"]), sum(i["score"] for i in doc["items"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))