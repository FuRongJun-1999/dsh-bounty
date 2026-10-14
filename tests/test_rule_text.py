# -*- coding: utf-8 -*-
"""守卫：口径文本一致性（真源对齐）——面向用户的**活文本**不得残留陈旧计分口径。

  python -X utf8 tests/test_rule_text.py            # 断言，末行「通过 N / 失败 M」
  python -X utf8 tests/test_rule_text.py --mutate    # 定点变异自证（每条须恰好命中期望红项）
  python -X utf8 tests/test_rule_text.py --list      # 只列变异表

为什么需要这一件：口径真源只有一处（`scripts/bounty_board.py` 的 `DIFFICULTY_SCORES` ／
`quality_delta` ／ `timeout_delta` ／ `invalid_delta`），而生成本仓面向文本的地方**有五个**
（README ／ 规则正文 ／ 发布模板 ／ board 生成器 ／ 站点生成器）。**真源改了、这些地方没跟着改**，
外部贡献者就会按旧口径预期自己的分（例如以为超时只扣 1 分，实际按 −2×base 扣 20 分）。
本件把「文本与真源一致」变成可机械复核、可反面证明的判据——不是靠人记得改。

判据分组（**各取独立信号**，避免一次红多组＝语义纠缠）：
  T1 现行口径**到位**：四处主要面向面必须写出 `−2×base`（改真源忘改文本 ⇒ 这里红）。
  T2 陈旧口径**不残留**：规则/榜面不得把超时写成 `−1`（`v0.1 分段生效`语境除外——
     那是历史事件的复算口径，必须保留）。
  T3 认领通道**单一**：真源 `howto` 的认领条与其渲染面必须同口径，且不含旧的绝对表述。

**扫描面（有意收窄，两个方向都写清以免读者以为漏了或错读）**：
  · **不含** `docs/spec/**`——设计史（各自带版本头，存在与现行口径不同的历史值，
    如 `悬赏站设计_v1.0` §4.4.3 的 `−max(1, base//2)`）。
  · **含** `docs/guide/悬赏站使用指南_v1.0.md`（★本件扩面）——它是**当前站的用法说明**，
    不是设计史；实测它曾残留 v0.1 的固定扣分（−1/−3/−5），与现行 `−2×base` 差 4–20 倍。
  · **不含** `tests/**`——守卫自身会**引用**陈旧口径作为变异描述（判据素材，不是对外文本）。
  · **不含** `progress` 流水（`悬赏.json` ／ `悬赏清单.md`）——进度是 append-only 历史记录，
    更正以**追加一行**表达（见真源 howto「更新进度」），不得回改历史行。
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.environ.get("BOUNTY_GUARD_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
QUIET = "--quiet" in sys.argv

#: T1 现行口径（`−2×base`）必须出现的四处主要面向面：精确锚点，避免「文件里别处有」算通过。
CURRENT_ANCHORS = (
    ("README.md", "超时未交付 −2×base"),
    ("docs/bounty/README.md", "记 **−2×base**"),
    (".github/ISSUE_TEMPLATE/bounty.yml", "记 **−2×base**"),
    ("site/rules.html", "超期自动回板并记 <b>−2×base</b>"),
)

#: T2 陈旧口径扫描面（规则/榜面 ＋ **两个生成器源**；不含 append-only 的进度流水）。
#: 为什么必须含源：产物陈旧时源往往**同样陈旧**——只扫产物＝源下次再生成又把旧口径写回页面。
#: ★本件扩面：把**面向外部贡献者的使用指南**纳入。原来整目录 `docs/guide/**` 被排除，
#: 理由是「版本化指南各自带版本头」—— 但 `悬赏站使用指南_v1.0.md` 是**当前站的用法说明**
#: （v1.0 就是现行版本），正是外部人照着预估自己分数的那份文档。
#: 实测：它的「超时未交付」两处仍写 **−1 / −3 / −5**（v0.1 的固定分），
#: 而现行 v0.4 是 **−2×base** ⇒ **−2 / −6 / −12 / −20**，差 4–20 倍 ——
#: 正是本件 docstring 举的那个例子（「以为超时只扣 1 分，实际扣 20 分」）。
#: 保留原有的**句子级白名单**（须同句含 `分段生效` 与 `v0.1` 才豁免），故设计史不受影响。
#: 《运行手册》§四-3 已把这一冲突列为盲区（「守卫扫描面与守卫目的相冲突」）。
STALE_SCAN = ("docs/bounty/board.md", "site/index.html", "site/honor.html",
              "scripts/bounty_board.py", "scripts/build_site.py",
              "docs/guide/悬赏站使用指南_v1.0.md")

#: 陈旧信号：超时与负数 1 同现。
# ★本件：补**数字边界**。旧式 `…\s*1(?:\s*分)?` 会**把 `−12`／`−10` 当成 `−1`** ——
# 实测：把指南里的超时扣分改正为现行 `−2×base`（含 `−12`）后，T2 **误报**「陈旧口径残留」。
# 也就是说旧式**分不清「扣 1 分」与「扣 12 分」**；而这两个值恰好是 v0.1 与 v0.4 的分界。
# `(?![0-9])` 要求 `1` 之后不是数字 ⇒ 只匹配真正的「1」。
STALE_RE = re.compile(r"超时[^\n]{0,40}?(?:−|-)\s*1(?![0-9])(?:\s*分)?")

#: 白名单：**命中所在的句子**须同时写明 `分段生效` **与** `v0.1`，才算**分段生效**的历史复算口径
#: （v0.1 旧事件按固定分复算，那个 −1 必须保留）。
#: 粒度为什么是句子而不是整行：`board.md` 的计分口径是**一整行**（既写现行 −2×base，
#: 又写「分段生效：v0.1 旧事件用固定分…超时 −1」）——按整行放行会把整行豁免掉，判据就空转了；
#: 而要求**两个**标记同时出现，则一句里只有「v0.1」不足以豁免（防用旧口径冒充历史说明）。
#: T3 真源认领条必须出现的两个信号（两条通道都要写明），以及**不得**出现的旧绝对表述。
CLAIM_MUST = ("仍开放", "PR")
CLAIM_MUST_NOT = "认领通道在 issue"

WHITELIST = ("分段生效", "v0.1")
SENT_SPLIT = "；;。\n"

_red = []


def ok(name, cond, detail=""):
    """判据：cond 为假即记红并点名（detail 供人查，不参与判定）。"""
    if not cond:
        _red.append(name.split(" ")[0])
    if QUIET:
        return
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                           "" if cond or not detail else "  ← %s" % detail))


def read(rel):
    return io.open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8").read()


def measure():
    m = {}
    m["anchors"] = [(rel, (anchor in read(rel)))
                    for rel, anchor in CURRENT_ANCHORS]
    stale = []
    for rel in STALE_SCAN:
        for i, line in enumerate(read(rel).splitlines(), 1):
            for sent in re.split("[" + SENT_SPLIT + "]", line):
                if all(w in sent for w in WHITELIST):
                    continue
                if STALE_RE.search(sent):
                    stale.append("%s:%d" % (rel, i))
    m["stale"] = stale
    doc = json.loads(read("docs/bounty/悬赏.json"))
    claim = doc["howto"][1]
    m["claim_src"] = claim
    m["claim_md"] = read("docs/bounty/悬赏清单.md")
    return m


def judge(m):
    del _red[:]
    miss = [rel for rel, hit in m["anchors"] if not hit]
    ok("T1 现行超时口径（−2×base）到位（四处主要面向面）", not miss, "缺：%s" % miss)
    ok("T2 陈旧超时口径（−1）不残留在规则/榜面与生成器源", not m["stale"],
       "命中：%s" % m["stale"])
    # 判据两面：真源 howto 与渲染面**都**须给出「通道取决于原 issue 是否仍开放」，
    # 且都不得残留旧的绝对表述（「认领通道在 issue，不在本清单」）。
    src_ok = (all(w in m["claim_src"] for w in CLAIM_MUST)
              and all(w in m["claim_md"] for w in CLAIM_MUST)
              and CLAIM_MUST_NOT not in m["claim_src"]
              and CLAIM_MUST_NOT not in m["claim_md"])
    ok("T3 认领通道表述与真源一致（两条通道同口径 ＋ 不含旧绝对表述）", src_ok,
       "howto[1]=%r" % m["claim_src"][:60])
    return list(_red)


# ---- 定点变异自证：把每条判据的锚点人为改坏 ⇒ 断言必须恰好变红并点名 ----

MUTATIONS = [
    ("R1", "site/rules.html",
     "超期自动回板并记 <b>−2×base</b>", "超期自动回板并记 −1", {"T1"}),
    ("R2", "README.md",
     "超时未交付 −2×base", "超时 −1", {"T1"}),
    ("R3", ".github/ISSUE_TEMPLATE/bounty.yml",
     "记 **−2×base**", "记 −1", {"T1"}),
    ("R4", "docs/bounty/README.md",
     "记 **−2×base**", "记 −1", {"T1"}),
    ("R5", "docs/bounty/board.md",
     "超时未交付 **−2×base**", "超时未交付 −1", {"T2"}),
    ("R6", "site/index.html",
     "超时自动回板（记 <b>−2×base</b>）", "超时自动回板（记 −1）", {"T2"}),
    ("R7", "scripts/build_site.py",
     "超时自动回板（记 <b>−2×base</b>）", "超时自动回板（记 −1）", {"T2"}),
    ("R8", "docs/bounty/悬赏.json",
     "**认领**：本清单**本身不接受认领**（它只是查看面）",
     "**认领**：在对应 **issue** 上评论 /claim。**认领通道在 issue，不在本清单**", {"T3"}),
]


def run_mutations():
    base = judge(measure())
    if base:
        print("基线就红，变异自证无意义：%s" % sorted(set(base)))
        return 1
    print("基线全绿（3 条断言）——开始定点变异自证")
    bad = []
    for mid, rel, old, new, expect in MUTATIONS:
        d = tempfile.mkdtemp(prefix="rule_text_")
        try:
            sandbox = os.path.join(d, "repo")
            shutil.copytree(ROOT, sandbox,
                            ignore=shutil.ignore_patterns(".git", "__pycache__"))
            p = os.path.join(sandbox, *rel.split("/"))
            t = io.open(p, encoding="utf-8").read()
            if old not in t:
                print("  [ANCHOR-MISS] %s 锚点不匹配（fail-closed，未写入）：%s" % (mid, rel))
                return 2
            io.open(p, "w", encoding="utf-8", newline="\n").write(t.replace(old, new, 1))
            r = subprocess.run(
                [sys.executable, "-X", "utf8", os.path.join(sandbox, "tests", "test_rule_text.py"),
                 "--quiet"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                         BOUNTY_GUARD_ROOT=sandbox), timeout=180)
            red = sorted(set(re.findall(r"^RED (\S+)", r.stdout or "", re.M)))
            if set(red) == set(expect):
                print("  [PASS] %s → %s" % (mid, ",".join(red)))
            else:
                print("  [FAIL] %s 期望 %s 实得 %s" % (mid, sorted(expect), red))
                bad.append(mid)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    print()
    print("定点变异：通过 %d / 失败 %d（共 %d）" % (len(MUTATIONS) - len(bad), len(bad),
                                                   len(MUTATIONS)))
    if bad:
        print("未命中：%s" % bad)
    return 0 if not bad else 1


def main():
    if "--list" in sys.argv:
        for mid, rel, old, new, expect in MUTATIONS:
            print("%s  %s  %s  ⇒ %s" % (mid, rel, old, "→".join(sorted(expect))))
        return 0
    if "--mutate" in sys.argv:
        return run_mutations()
    red = judge(measure())
    if QUIET:
        for r in sorted(set(red)):
            print("RED %s" % r)
        return 1 if red else 0
    print()
    print("通过 %d / 失败 %d" % (3 - len(set(red)), len(set(red))))
    if red:
        print("红项：%s" % sorted(set(red)))
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
