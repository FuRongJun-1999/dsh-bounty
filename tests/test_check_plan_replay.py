# -*- coding: utf-8 -*-
"""守卫：悬赏清单「复跑命令」必须真的能跑通（#66 bounty-pm 验收原文 vs 实现）。

缺陷：悬赏.json 的 acceptance 第 1 条写明
    python -X utf8 scripts/check_plan.py --dry-run  （退出码 0）
但 check_plan.py 的 --dry-run 缺省读 docs/bounty/issues-state.json，
而该文件**从未提交进仓**（git log --all 空、origin/main tree 无）⇒
在**任何干净检出**上，验收原文这条命令**必定 rc=1**。

跑法：
  python -X utf8 tests/test_check_plan_replay.py
  python -X utf8 tests/test_check_plan_replay.py --mutate
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(REPO, "scripts", "check_plan.py")
BOUNTY_JSON = os.path.join(REPO, "docs", "bounty", "\u60ac\u8d4f.json")
BOUNTY_MD = os.path.join(REPO, "docs", "bounty", "\u60ac\u8d4f\u6e05\u5355.md")

PASS = 0
FAIL = 0
MUTATE = "--mutate" in sys.argv


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + name)
    else:
        FAIL += 1
        print("  [FAIL] " + name + (" :: " + detail if detail else ""))


def run(argv):
    proc = subprocess.run([sys.executable, "-X", "utf8", SCRIPT] + argv,
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def acceptance_of(bid):
    with open(BOUNTY_JSON, encoding="utf-8") as fh:
        doc = json.load(fh)
    for it in doc.get("items") or []:
        if it.get("id") == bid:
            return it.get("acceptance") or []
    return []


print("== A \u9a8c\u6536\u539f\u6587\u547d\u4ee4\u5728\u5e72\u51c0\u68c0\u51fa\u4e0a\u662f\u5426\u771f\u7684 rc=0 ==")
rc, out = run(["--dry-run"])
SNAP_MISSING = ("[error]" in out) and ("issues-state.json" in out)

acc = acceptance_of("bounty-pm")
acc_txt_all = " ".join(acc)
md_txt = ""
if os.path.exists(BOUNTY_MD):
    with open(BOUNTY_MD, encoding="utf-8") as fh:
        md_txt = fh.read()
#: \u9a8c\u6536\u539f\u6587\uff08acceptance \u6216\u751f\u6210\u7269\uff09\u662f\u5426\u5199\u660e\u4e86\u300c\u5148\u5bfc\u51fa\u5feb\u7167\u300d\u8fd9\u4e00\u524d\u7f6e
HAS_PREREQ = ("check_plan_snapshot" in acc_txt_all) or ("check_plan_snapshot" in md_txt)

#: \u5173\u952e\u5224\u636e\uff1a\u547d\u4ee4\u8981\u4e48\u76f4\u63a5\u8dd1\u901a\uff0c\u8981\u4e48\u56e0\u300c\u5feb\u7167\u672a\u5bfc\u51fa\u300d\u800c\u62a5\u9519\u4e14\u539f\u6587\u5df2\u5199\u660e\u524d\u7f6e\u3002
#: \u4e24\u8005\u90fd\u4e0d\u6ee1\u8db3 \u21d2 \u9a8c\u6536\u539f\u6587\u7684\u6307\u4ee4\u5728\u5e72\u51c0\u68c0\u51fa\u4e0a\u4e0d\u53ef\u6267\u884c\uff08\u672c\u4ef6\u7f3a\u9677\uff09\u3002
EXECUTABLE = (rc == 0) or (SNAP_MISSING and HAS_PREREQ)
ok("A1 \u9a8c\u6536\u539f\u6587\u547d\u4ee4\u5728\u5e72\u51c0\u68c0\u51fa\u4e0a\u53ef\u6267\u884c\uff08\u76f4\u63a5 rc=0\uff0c\u6216\u5199\u660e\u524d\u7f6e\uff09",
   EXECUTABLE, "rc=" + str(rc) + " snap_missing=" + str(SNAP_MISSING) + " prereq=" + str(HAS_PREREQ))
ok("A2 \u4e0d\u7528\u6837\u4f8b\u5192\u5145\u4ed3\u5185\u5b9e\u9645\u72b6\u6001\uff08\u82e5\u5feb\u7167\u7f3a\u5931\u5219\u5fc5\u987b\u54cd\u4eae\u62a5\u9519\uff0c\u4e0d\u5f97\u9759\u9ed8\u56de\u9000\u5939\u5177\uff09",
   (rc == 0) or SNAP_MISSING,
   "rc=" + str(rc) + " out=" + out[:200])

print()
print("== B \u82e5\u4f9d\u8d56\u4e0d\u5165\u4ed3\u4ea7\u7269\uff0c\u9a8c\u6536\u539f\u6587\u987b\u5199\u660e\u524d\u7f6e\u6b65\u9aa4 ==")
replay = [x for x in acc if "check_plan.py --dry-run" in x]
ok("B1 acceptance \u91cc\u80fd\u627e\u5230\u590d\u8dd1\u547d\u4ee4\u539f\u6587", bool(replay), "n=" + str(len(acc)))
ok("B2 \u590d\u8dd1\u547d\u4ee4\u5199\u660e\u524d\u7f6e\uff08check_plan_snapshot.py \u5148\u5bfc\u51fa\u5feb\u7167\uff09", HAS_PREREQ,
   "acceptance \u4e0e \u60ac\u8d4f\u6e05\u5355.md \u90fd\u672a\u63d0 check_plan_snapshot")

print()
print("== C \u53cd\u5411\uff1a\u811a\u672c\u672c\u8eab\u6ca1\u574f\uff08\u663e\u5f0f\u5939\u5177 rc=0\uff09 ==")
led = os.path.join(REPO, "tests", "fixtures", "check_plan_golden_ledger.json")
iss = os.path.join(REPO, "tests", "fixtures", "check_plan_golden.json")
if os.path.exists(led) and os.path.exists(iss):
    rc2, out2 = run(["--dry-run", "--ledger", led, "--issues", iss])
    ok("C1 \u663e\u5f0f\u7ed9\u5939\u5177 \u21d2 rc=0\uff08\u7f3a\u7684\u662f\u7f3a\u7701\u6e90\uff0c\u4e0d\u662f\u811a\u672c\uff09", rc2 == 0, "rc=" + str(rc2))
    ok("C2 \u663e\u5f0f\u5939\u5177\u65f6\u786e\u5b9e\u6253\u5370\u4e09\u65b9\u8868", ("\u6807\u7b7e\u6001" in out2) and ("\u8d26\u672c\u6001" in out2), out2[:120])
else:
    ok("C1 \u5939\u5177\u5b58\u5728", False, "fixtures \u7f3a\u5931")

print()
print("== R \u5b9a\u70b9\u53d8\u5f02\uff1a\u64a4\u6389\u300c\u7f3a\u7701\u6e90\u53ef\u5f97\u300d\u8fd9\u4e00\u524d\u63d0\uff0cA1 \u5fc5\u8f6c\u7ea2 ==")
if MUTATE:
    snap = os.path.join(REPO, "docs", "bounty", "issues-state.json")
    fixture = os.path.join(REPO, "tests", "fixtures", "check_plan_golden.json")
    had = os.path.exists(snap)
    backup = None
    if had:
        with open(snap, "rb") as fh:
            backup = fh.read()
    #: \u5148\u9020\u51fa\u5feb\u7167\uff08\u6a21\u62df\u300c\u5df2\u8dd1\u8fc7\u5bfc\u51fa\u300d\u7684\u68c0\u51fa\uff09\uff0c\u786e\u8ba4 rc=0
    with open(fixture, "rb") as fh:
        payload = fh.read()
    with open(snap, "wb") as fh:
        fh.write(payload)
    rc_before = run(["--dry-run"])[0]
    ok("R1 \u5b58\u5728\u5feb\u7167\u65f6 --dry-run rc=0\uff08\u6b63\u5e38\u8def\u5f84\uff09", rc_before == 0, "before=" + str(rc_before))
    #: \u64a4\u6389\u5feb\u7167 \u21d2 \u5fc5\u987b\u8f6c 1\uff08\u8bc1\u660e A1 \u786e\u5b9e\u4f9d\u8d56\u5b83\uff0c\u4e0d\u662f\u6052\u771f\uff09
    os.remove(snap)
    rc_after = run(["--dry-run"])[0]
    ok("R2 \u64a4\u6389\u5feb\u7167\u540e rc \u8f6c 1\uff08\u53d8\u5f02\u81ea\u8bc1\uff09", rc_after == 1, "after=" + str(rc_after))
    #: \u6062\u590d\u539f\u72b6
    if backup is not None:
        with open(snap, "wb") as fh:
            fh.write(backup)
    print("  \u53d8\u5f02\u81ea\u8bc1\uff1a2/2")
else:
    print("  \uff08\u8df3\u8fc7\uff1b\u52a0 --mutate \u8dd1\u53cd\u9762\u8bc1\u660e\uff09")

print()
print("  \u901a\u8fc7 " + str(PASS) + " / \u5931\u8d25 " + str(FAIL))
if FAIL:
    print("  RESULT: RED")
    sys.exit(1)
print("  RESULT: GREEN")
