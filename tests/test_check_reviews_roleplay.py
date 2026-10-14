# -*- coding: utf-8 -*-
"""tests/test_check_reviews_roleplay.py —— 守卫 scripts/check_reviews_roleplay.py 的判别力自证。

做什么：在 tempfile 临时目录里自造最小沙箱（4 份交付报告 + raw/*.txt + raw/*_summary.json
+ out/*.json + data/{worldbook.json,chat.jsonl}），先跑正向（必须 13/0），再对**沙箱副本**
逐条施加定点变异，断言**恰好**打红预期的那几条判据：多红 = 判据语义纠缠，少红 = 该判据空转。

夹具由本文件自带的最小 writer 生成，不 import bench/ 下任何模块，也不依赖 spike/ 是否存在。

用法：
  python -X utf8 tests/test_check_reviews_roleplay.py                  # 正向 + 全部定点变异
  python -X utf8 tests/test_check_reviews_roleplay.py --mutate=R8b     # 只跑一条变异并打印红项集
  python -X utf8 tests/test_check_reviews_roleplay.py --quiet          # 只输出 RED <名> 与 RAN <n>
  python -X utf8 tests/test_check_reviews_roleplay.py --root <dir>     # 指定仓库根（默认本仓库）
退出码：0 全绿；1 有失败项；2 变异锚点缺失（ANCHOR-MISS）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)
GUARD_REL = os.path.join("scripts", "check_reviews_roleplay.py")
FENCE = chr(96) * 3

SCHEMES = [("SillyTavern", "sillytavern"), ("RisuAI", "risuai"), ("diceframe", "diceframe")]
METHOD = "测评方法论_角色扮演_v0.1.md"
BASELINE = "baseline"

#: 仓库夹具指纹（只做一致性核对，不参与判据；见 check_g2_data_fingerprint）。
REPO_WORLDBOOK_SHA = "e5614804d895d0aee40a0d696589dccb844801773b9e6f8a85709e0f5407b093"
REPO_CHAT_SHA = "e36f47a523868089d7c93dcb9744aec4dcf5b565b1c3ea799877fd4b3ac9efa5"

#: 报告与方法论模板。__FENCE__ 换成三反引号，__S__/__L__/__SHAWB__/__SHACHAT__ 按方案替换。
#: 模板里刻意让围栏内的读数行只在对应 raw/*.txt 里出现一次，且全文不含 BANNED 词。
REPORT = u"""# __S__ 角色扮演适配器测评 v0.1

## 0. 结论摘要

- P0 逐 turn 激活集与基线一致，无差异（M1）。
- 注入顺序在同激活集上与基线相同（M2）。
- P3 档 dropped_uids 比 P0 多 1 条（M3）。
- 重复 8 次输出 sha256 逐字节一致（M6）。

## 1. 被测对象与版本

仓库 https://example.invalid/__L__ ，commit sha=0123456789abcdef0123456789abcdef01234567。

## 2. 复现步骤

__FENCE__bash
python -X utf8 bench/roleplay_eval/adapters/run___S__.py --profile P0
__FENCE__

## 3. 基线 vs 方案对照读数

__FENCE__text
READOUT __S__ P0 turn=1 active=3 order=u1,u2,u3 chars=120 bytes=140 dropped=-
DIFF baseline __S__ P0 turn=1 only_a=- only_b=- same=3
__FENCE__

## 4. 读数明细

逐 turn 读数见 raw/__S___P0.txt，不确定性复跑见 raw/__S___repeat.txt。
本适配器未实现 tokenizer 字段，按 CONTRACT 第 6 节记 unsupported，依据见 raw/__S___summary.json。

__FENCE__text
CAPS __S__ {"recursive":true,"group":true,"probability":true,"regex_key":false,"at_depth":true}
TIMING __S__ profile=P0 min_ms=40.1 p50_ms=41.2 p95_ms=43.3
__FENCE__

## 5. 不适用条件

本档不适用条件：上游未提供概率调节接口，probability 档位不参与对照，读数按缺省值处理。

## 6. 未测项与原因

未测项：长会话（超过 200 turn）下的注入顺序稳定性未测，原因是夹具 chat.jsonl 只覆盖 2 turn。
"""

METHOD_TEXT = u"""# 角色扮演横向测评方法论 v0.1

## 1. 范围

本方法论覆盖 docs/reviews/ 下三份角色扮演方案报告的读数口径与复现步骤。

## 2. 读数项

读数项 M1 至 M8 定义如下：M1 激活集、M2 注入顺序、M3 预算溢出、M4 递归消融、M5 深度消融、M6 确定性、M7 匹配口径消融、M8 代价。

## 3. 公平性规则

三份方案共用同一夹具与同一 profile 集合，差异只允许来自适配器实现；基线读数记在本方法论。

## 4. 复现步骤（第三方原样可跑）

__FENCE__bash
python -X utf8 bench/roleplay_eval/harness/runner.py --adapter baseline --profile P0
__FENCE__

## 5. 夹具指纹

data/worldbook.json 的 sha256 = __SHAWB__；data/chat.jsonl 的 sha256 = __SHACHAT__。两值由 sha256sum 直接读出，不得手写。

## 6. 基线读数

__FENCE__text
READOUT baseline P0 turn=1 active=2 order=b1,b2 chars=88 bytes=99 dropped=-
__FENCE__

基线不支持的字段：regex_key，理由见 raw/baseline_summary.json。

## 7. 读数行语法

读数行前缀固定，sha256 一律 64 位小写十六进制，空集合写短横线。原始日志见 raw/baseline_P0.txt。

## 8. 不适用条件

温度与 top_p 在引擎内不可分别设置，故本方法论不设该维度的对照读数，相关档位一律不适用。

## 9. 未测项与原因

未测项：跨引擎 token 计数未测，原因是各家分词器口径不同，跨引擎比较无意义。
"""


class AnchorMiss(Exception):
    """变异锚点缺失：夹具改过或判据改过，变异已无判别力。"""


def sha256_text(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def read(p):
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write(p, t):
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(t)


def sub(root, rel, old, new):
    """定点替换一次；锚点缺失即 AnchorMiss（不许静默跳过）。"""
    p = os.path.join(root, rel)
    t = read(p)
    if old not in t:
        raise AnchorMiss("%s 未命中锚点：%r" % (rel, old[:50]))
    write(p, t.replace(old, new, 1))


# ---------------------------------------------------------------- 夹具构造

def build_fixture(root):
    """造最小沙箱；返回 data 两份夹具的 sha256。"""
    reviews = os.path.join(root, "docs", "reviews")
    bench = os.path.join(root, "bench", "roleplay_eval")
    raw = os.path.join(bench, "raw")
    out = os.path.join(bench, "out")
    data = os.path.join(bench, "data")
    for d in (reviews, raw, out, data):
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)

    wb = json.dumps({"entries": [{"uid": 1, "name": "测试世界书", "keys": ["测试"]}]},
                    ensure_ascii=False, indent=2) + "\n"
    chat = (json.dumps({"i": 0, "role": "user", "text": "外面在下雨。"}, ensure_ascii=False) + "\n"
            + json.dumps({"i": 1, "role": "assistant", "text": "我撑伞走过去。"}, ensure_ascii=False) + "\n")
    write(os.path.join(data, "worldbook.json"), wb)
    write(os.path.join(data, "chat.jsonl"), chat)

    for name, low in SCHEMES:
        readout = ("READOUT %s P0 turn=1 active=3 order=u1,u2,u3 chars=120 bytes=140 dropped=-\n"
                   "READOUT %s P0 turn=2 active=2 order=u2,u3 chars=90 bytes=101 dropped=-\n" % (name, name))
        write(os.path.join(raw, "%s_P0.txt" % name),
              readout
              + "CAPS %s {\"recursive\":true,\"group\":true,\"probability\":true,\"regex_key\":false,\"at_depth\":true}\n" % name
              + "TIMING %s profile=P0 min_ms=40.1 p50_ms=41.2 p95_ms=43.3\n" % name
              + "SUMMARY adapter=%s profiles=1 failures=0\n" % name)
        write(os.path.join(raw, "%s_baseline_diff.txt" % name),
              "DIFF baseline %s P0 turn=1 only_a=- only_b=- same=3\n"
              "DIFF baseline %s P0 turn=2 only_a=u4 only_b=- same=2\n" % (name, name))
        write(os.path.join(raw, "%s_repeat.txt" % name),
              "DETERMINISM %s repeats=8 identical=true sha=%s\n" % (name, sha256_text(name)[:64]))
        write(os.path.join(raw, "%s_summary.json" % name), json.dumps({
            "adapter": name,
            "profiles": {"P0": {"errors": [],
                                "unsupported": [{"field": "regex_key", "reason": "no-regex-key"}]}},
            "determinism": {"P0": {"identical": True, "repeats": 8, "sha": sha256_text(name)}},
        }, ensure_ascii=False, indent=2) + "\n")
        write(os.path.join(out, "%s_P0.json" % name), json.dumps({
            "adapter": low, "profile": "P0",
            "unsupported": [{"field": "tokenizer", "reason": "no-native-tokenizer"}],
        }, ensure_ascii=False, indent=2) + "\n")
        write(os.path.join(reviews, "%s_v0.1.md" % name),
              REPORT.replace("__S__", name).replace("__L__", low).replace("__FENCE__", FENCE))

    write(os.path.join(raw, "%s_P0.txt" % BASELINE),
          "READOUT baseline P0 turn=1 active=2 order=b1,b2 chars=88 bytes=99 dropped=-\n"
          "TIMING baseline profile=P0 min_ms=41.4 p50_ms=41.9 p95_ms=43.2\n"
          "SUMMARY adapter=baseline profiles=1 failures=0\n")
    write(os.path.join(raw, "%s_summary.json" % BASELINE), json.dumps({
        "adapter": BASELINE,
        "profiles": {"P0": {"errors": [],
                            "unsupported": [{"field": "regex_key", "reason": "baseline-literal-key"}]}},
        "determinism": {"P0": {"identical": True, "repeats": 8, "sha": sha256_text(BASELINE)}},
    }, ensure_ascii=False, indent=2) + "\n")
    write(os.path.join(out, "%s_P0.json" % BASELINE), json.dumps({
        "adapter": BASELINE,
        "unsupported": [{"field": "regex_key", "reason": "baseline-literal-key"}],
    }, ensure_ascii=False, indent=2) + "\n")
    write(os.path.join(reviews, METHOD),
          METHOD_TEXT.replace("__FENCE__", FENCE)
                     .replace("__SHAWB__", sha256_text(wb))
                     .replace("__SHACHAT__", sha256_text(chat)))
    return sha256_text(wb), sha256_text(chat)


# ---------------------------------------------------------------- 定点变异

def m_r1(root):
    """R1：把 diceframe 报告改名（等价于该交付件缺失）。"""
    rv = os.path.join(root, "docs", "reviews")
    os.replace(os.path.join(rv, "diceframe_v0.1.md"), os.path.join(rv, "diceframe_v0.2.md"))


def m_r2(root):
    """R2：把 SillyTavern 报告的 §3 与 §4 调换，七个标题顺序不再一致。"""
    p = os.path.join(root, "docs", "reviews", "SillyTavern_v0.1.md")
    t = read(p)
    i3 = t.index("\n## 3. 基线 vs 方案对照读数")
    i4 = t.index("\n## 4. 读数明细")
    i5 = t.index("\n## 5. 不适用条件")
    write(p, t[:i3] + t[i4:i5] + t[i3:i4] + t[i5:])


def m_r3(root):
    """R3 第一子句：方法论 §7 的编号点号被删，九节编号不再齐备。"""
    sub(root, os.path.join("docs", "reviews", METHOD), "## 7. 读数行语法", "## 7 读数行语法")


def m_r3b(root):
    """R3 第二子句：编号仍在，但具名标题「公平性规则」被改，五个具名标题不再逐字存在。"""
    sub(root, os.path.join("docs", "reviews", METHOD), "## 3. 公平性规则", "## 3. 公平规则")


def m_r4(root):
    """R4：报告引用一个 raw/ 下不存在的证据文件。"""
    p = os.path.join(root, "docs", "reviews", "SillyTavern_v0.1.md")
    write(p, read(p) + "\n另见 raw/SillyTavern_P9.txt 的逐字日志。\n")


def m_r5(root):
    """R5：围栏里加一条 raw/*.txt 指不到的新读数行。"""
    sub(root, os.path.join("docs", "reviews", "SillyTavern_v0.1.md"),
        "TIMING SillyTavern profile=P0 min_ms=40.1 p50_ms=41.2 p95_ms=43.3",
        "TIMING SillyTavern profile=P0 min_ms=40.1 p50_ms=41.2 p95_ms=43.3\n"
        "KPI latency_ms value=41.0 ci=[40.1,43.3] n=8")


def m_r6(root):
    """R6：报告里出现不可判词。"""
    p = os.path.join(root, "docs", "reviews", "RisuAI_v0.1.md")
    #: 命中守卫 BANNED[0]（U+770B U+8D77 U+6765 U+66F4 U+597D），只看判据不看措辞。
    banned = "\u770b\u8d77\u6765\u66f4\u597d"
    write(p, read(p) + "\n" + "\u957f\u4f1a\u8bdd\u4e0b\u672c\u65b9\u6848" + banned + "\u3002\n")


def m_r7(root):
    """R7：§2 的适配器命令换成不能原样执行的脚本。"""
    sub(root, os.path.join("docs", "reviews", "SillyTavern_v0.1.md"),
        "python -X utf8 bench/roleplay_eval/adapters/run_SillyTavern.py --profile P0",
        "bash scripts/run_adapter.sh --profile P0")


def m_r8(root):
    """R8 第一触发面：summary 里某档 determinism.identical=false，报告无同行披露。"""
    p = os.path.join(root, "bench", "roleplay_eval", "raw", "SillyTavern_summary.json")
    obj = json.loads(read(p))
    obj["determinism"]["P0"]["identical"] = False
    write(p, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def m_r8b(root):
    """R8 第二触发面：某档 errors 非空，报告同样没有同行披露。"""
    p = os.path.join(root, "bench", "roleplay_eval", "raw", "SillyTavern_summary.json")
    obj = json.loads(read(p))
    obj["profiles"]["P0"]["errors"] = ["engine shim returned status=3"]
    write(p, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def m_r9(root):
    """R9：方法论正文的夹具 sha256 被改成假值（围栏内没有副本可供掩盖）。"""
    p = os.path.join(root, "docs", "reviews", METHOD)
    t = read(p)
    key = "data/worldbook.json 的 sha256 = "
    i = t.index(key) + len(key)
    if re.fullmatch(r"[0-9a-f]{64}", t[i:i + 64]) is None:
        raise AnchorMiss("方法论正文的 worldbook sha256 不是 64 位十六进制")
    write(p, t[:i] + "a" * 64 + t[i + 64:])


def m_r10(root):
    """R10：§6 只剩标题，正文里没有「未测」。"""
    #: 只清 §6 正文里的「未测」：七个二级标题（含「未测项与原因」）必须原样留着，
    #: 否则会连带给 R2 打红（标题串同为 R2 的必需项），R10 就不再是定点变异。
    sub(root, os.path.join("docs", "reviews", "SillyTavern_v0.1.md"),
        "\u672a\u6d4b\u9879\uff1a\u957f\u4f1a\u8bdd\uff08\u8d85\u8fc7 200 turn\uff09\u4e0b\u7684\u6ce8\u5165\u987a\u5e8f\u7a33\u5b9a\u6027\u672a\u6d4b\uff0c\u539f\u56e0\u662f\u5939\u5177 chat.jsonl \u53ea\u8986\u76d6 2 turn\u3002",
        "\u957f\u4f1a\u8bdd\u7a33\u5b9a\u6027\u672c\u8f6e\u6ca1\u6709\u8986\u76d6\u3002")


def m_r11(root):
    """R11：§5 正文压到 40 字符以下。"""
    p = os.path.join(root, "docs", "reviews", "SillyTavern_v0.1.md")
    t = read(p)
    h = "## 5. 不适用条件"
    i = t.index(h) + len(h)
    j = t.index("\n## 6. 未测项与原因")
    write(p, t[:i] + "\n\n本档无。\n" + t[j:])


def m_r12(root):
    """R12：§0 有一条结论项丢掉 M 引用。"""
    sub(root, os.path.join(root, "docs", "reviews", "SillyTavern_v0.1.md"),
        "- 注入顺序在同激活集上与基线相同（M2）。",
        "- 注入顺序在同激活集上与基线相同。")


def m_r13(root):
    """R13：out/*.json 的 unsupported field 从对应报告正文消失。"""
    sub(root, os.path.join(root, "docs", "reviews", "SillyTavern_v0.1.md"),
        "未实现 tokenizer 字段", "未实现分词器字段")


#: 变异 -> 期望被打红的判据集合。必须**恰好**相等：多红 = 判据语义纠缠，少红 = 该判据空转。
#: R1 的期望集合是「删一份方案报告」的**扇出集**，与守卫实现一致：文本缺失时该报告的逐报告
#: 判据 R2/R4/R5/R6/R7/R8/R10/R11 在 checks() 里显式一并打红（fail-closed，不许静默跳过），
#: out/<方案>_P0.json 的 R13 因对应文档查不到也打红；R12 在文本缺失时同样被 R2 分支之外的
#: 文本遍历前置检查覆盖（§0 无从核对即红）；R9 只核方法论，故不红。
MUTATIONS = [
    ("R1", {"R1", "R2", "R4", "R5", "R6", "R7", "R8", "R10", "R11", "R12", "R13"}, m_r1),
    ("R2", {"R2"}, m_r2),
    ("R3", {"R3"}, m_r3),
    ("R3b", {"R3"}, m_r3b),
    ("R4", {"R4"}, m_r4),
    ("R5", {"R5"}, m_r5),
    ("R6", {"R6"}, m_r6),
    ("R7", {"R7"}, m_r7),
    ("R8", {"R8"}, m_r8),
    ("R8b", {"R8"}, m_r8b),
    ("R9", {"R9"}, m_r9),
    ("R10", {"R10"}, m_r10),
    ("R11", {"R11"}, m_r11),
    ("R12", {"R12"}, m_r12),
    ("R13", {"R13"}, m_r13),
]
MUT_IDS = [m[0] for m in MUTATIONS]


# ---------------------------------------------------------------- 跑守卫

def guard_path(root):
    return os.path.join(root, GUARD_REL)


def run_guard(root, env_root):
    """用 env_root 里的守卫跑 fixture 根 root；返回 (red 列表, RAN, 退出码, stdout)。"""
    cmd = [sys.executable, "-X", "utf8", guard_path(env_root),
           "--root", root, "--quiet"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode("utf-8", "replace")
    red = sorted(l.split()[1] for l in out.splitlines() if l.startswith("RED "))
    ran = [l.split()[1] for l in out.splitlines() if l.startswith("RAN ")]
    return red, (ran[0] if ran else "0"), p.returncode, out


def scratch_copy(root):
    d = tempfile.mkdtemp(prefix="roleplay-check-")
    build_fixture(d)
    return d


# ---------------------------------------------------------------- 主流程

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--mutate", default=None, help="只跑一条变异（见 MUT_IDS）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    if not os.path.isfile(guard_path(root)):
        print("找不到守卫：%s" % guard_path(root))
        return 2
    if args.mutate and args.mutate not in MUT_IDS:
        print("未知变异：%s（可选：%s）" % (args.mutate, ",".join(MUT_IDS)))
        return 2

    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    # A0 夹具自检：自带 writer 造出来的夹具必须真的落盘
    d0 = scratch_copy(root)
    try:
        need = [os.path.join("docs", "reviews", fn) for fn in
                ["%s_v0.1.md" % n for n, _ in SCHEMES] + [METHOD]]
        need += [os.path.join("bench", "roleplay_eval", "raw", "SillyTavern_P0.txt"),
                 os.path.join("bench", "roleplay_eval", "raw", "baseline_summary.json"),
                 os.path.join("bench", "roleplay_eval", "out", "baseline_P0.json"),
                 os.path.join("bench", "roleplay_eval", "data", "worldbook.json"),
                 os.path.join("bench", "roleplay_eval", "data", "chat.jsonl")]
        missing = [rel for rel in need if not os.path.isfile(os.path.join(d0, rel))]
        check("A0 沙箱夹具齐备（4 报告 + raw + out + data）", not missing,
              "缺=%s" % missing)

        if args.mutate is None:
            # A1 正向：沙箱全绿（退出码 0 且 stdout 无 RED 行）
            red, ran, rc, out = run_guard(d0, root)
            check("A1 正向：临时沙箱全绿（rc=0 且无 RED 行）",
                  rc == 0 and red == [] and "RED " not in out and ran == "13",
                  "rc=%s 红项=%s" % (rc, red))
            # A1b/A1c/A1d（#396）：R8 的 raw 路径解析必须「大小写精确」。
            # 为什么放这里：Windows 大小写不敏感 ⇒ 旧写法在本机能碰巧找到文件，只有 Linux 才暴露；
            # 故断言必须与文件系统无关，否则「本地绿 / CI 红」永远抓不住。
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location("crr_mod", guard_path(root))
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _src = open(guard_path(root), encoding="utf-8").read()
            check("A1c 旧写法（显示名直接拼路径）已不在源码",
                  'os.path.join(raw, "%s_summary.json" % name)' not in _src)
            _rawabs = os.path.join(d0, "bench", "roleplay_eval", "raw")
            _actual = set(os.listdir(_rawabs))
            _bad = []
            for _rfn, _disp in _mod.SCHEME_REPORTS.items():
                _pp = _mod.find_summary(_rawabs, _disp)
                if _pp is None or os.path.basename(_pp) not in _actual:
                    _bad.append("%s->%s" % (_disp, _pp))
            check("A1b R8 路径解析大小写精确（沙箱）", not _bad, "非精确=%s" % _bad)
            _rraw = os.path.join(root, "bench", "roleplay_eval", "raw")
            if os.path.isdir(_rraw):
                _ract = set(os.listdir(_rraw))
                _rbad = []
                for _rfn2, _disp2 in _mod.SCHEME_REPORTS.items():
                    _q = _mod.find_summary(_rraw, _disp2)
                    if _q is None or os.path.basename(_q) not in _ract:
                        _rbad.append("%s->%s" % (_disp2, _q))
                check("A1d 真仓库 raw/ 三条方案 summary 均可精确解析（#396）", not _rbad,
                      "非精确=%s" % _rbad)
    finally:
        if not args.keep:
            shutil.rmtree(d0, ignore_errors=True)

    # A2..An 逐条定点变异：一条变异 = 一个独立沙箱
    for mid, expect, fn in MUTATIONS:
        if args.mutate and args.mutate != mid:
            continue
        d = scratch_copy(root)
        try:
            try:
                fn(d)
            except AnchorMiss as e:
                check("A-%s 变异锚点存在" % mid, False, "ANCHOR-MISS %s" % e)
                continue
            red, ran, rc, out = run_guard(d, root)
            check("A-%s 变异恰好打红 %s" % (mid, ",".join(sorted(expect, key=lambda s: int(s[1:])))),
                  set(red) == expect,
                  "实际=%s 期望=%s" % (",".join(red), ",".join(sorted(expect, key=lambda s: int(s[1:])))))
        finally:
            if not args.keep:
                shutil.rmtree(d, ignore_errors=True)

    # G2 判据数自证：--list 条数 >=13 且无重复
    p = subprocess.run([sys.executable, "-X", "utf8", guard_path(root), "--list"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    ids = [l.strip() for l in p.stdout.decode("utf-8", "replace").splitlines() if l.strip()]
    check("G2 --list 判据数 >=13 且无重复",
          len(ids) >= 13 and len(set(ids)) == len(ids), "判据=%d 去重后=%d" % (len(ids), len(set(ids))))

    # G3 仓库夹具指纹一致性（可选核对：只在本仓库存在真夹具时执行，不作为失败项）
    wb = os.path.join(root, "bench", "roleplay_eval", "data", "worldbook.json")
    ct = os.path.join(root, "bench", "roleplay_eval", "data", "chat.jsonl")
    note = "not-present"
    if os.path.isfile(wb) and os.path.isfile(ct):
        note = "worldbook=%s chat=%s" % (sha256_file(wb) == REPO_WORLDBOOK_SHA,
                                         sha256_file(ct) == REPO_CHAT_SHA)

    nfail = sum(1 for _, ok, _ in results if not ok)
    if args.quiet:
        for name, ok, _ in results:
            if not ok:
                print("RED %s" % name)
        print("RAN %d" % len(results))
        print("通过 %d / 失败 %d" % (len(results) - nfail, nfail))
        return 1 if nfail else 0
    for name, ok, detail in results:
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           ("  <- " + detail) if detail and not ok else ""))
    print("仓库夹具指纹核对：%s" % note)
    print("通过 %d / 失败 %d" % (len(results) - nfail, nfail))
    return 1 if nfail else 0


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AnchorMiss as e:
        print("ANCHOR-MISS %s" % e)
        sys.exit(2)
