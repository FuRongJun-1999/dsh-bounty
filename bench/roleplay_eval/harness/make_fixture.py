#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成规范工作负载（CONTRACT.md §1）。

产物固定三个文件：
  data/worldbook.json  世界书条目 uid1-23（规范）＋ uid24/25（能力探针）
  data/chat.jsonl      12 条消息，6 个评估轮（turn k 喂前 2k 条）
  data/profiles.json   5 个设置档 P0-P4

生成器无随机数：同版本两次运行产物逐字节相同。
§1.2 受控事实逐条断言；任一不满足即退出码 1。

实现口径（契约未写死、由本文件固定并公开）：
  - §1.1 标题写「22 条」，表内实为 25 行（uid1-23 ＋ 24/25 探针）：按表实现。
  - 除 uid12 外，全部正文不含任何触发键，递归探针单点可归因。
  - 每行注释与 uid 一一对应，comment 不参与匹配。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SEED = 20261014
RECURSIVE_MAX_DEPTH = 3
SCHEMA_WORLDBOOK = "roleplay-eval-worldbook/1"
SCHEMA_PROFILES = "roleplay-eval-profiles/1"


def entry(uid, comment, content, *, keys=(), secondary_keys=(), selective=False,
          logic="and_any", enabled=True, constant=False, order=100,
          position="before_char", depth=None, probability=100,
          case_sensitive=False, match_whole_words=False, group=None,
          group_weight=100, recursion_exclude=False, capability_probe=False):
    """按 §3.1 字段集造一条条目。缺省值即契约缺省。"""
    return {
        "uid": uid,
        "comment": comment,
        "content": content,
        "keys": list(keys),
        "secondary_keys": list(secondary_keys),
        "selective": selective,
        "selective_logic": logic,
        "enabled": enabled,
        "constant": constant,
        "order": order,
        "position": position,
        "depth": depth,
        "probability": probability,
        "case_sensitive": case_sensitive,
        "match_whole_words": match_whole_words,
        "group": group,
        "group_weight": group_weight,
        "recursion": {"exclude": recursion_exclude, "prevent": False, "delay": False},
        "capability_probe": capability_probe,
    }


# 900 字符常驻正文：固定段落重复后截断，无触发键，无 ASCII。
_PARA_44 = "石阶顺着坡道往上，两侧是矮墙与青苔。风从湖面推过来，带着凉气。远处有钟声，一下，又一下。"
C20 = (_PARA_44 * 21)[:900]

# 56 字符 / 168 字节：与 CONTRACT §3.2 示例里的 uid1 读数同口径。
C1 = "常驻摘要：本节只记环境与叙事语气，不含任何触发词，每轮无条件注入。正文只作计数与排序用途。本条仅作占位说明用途。"

WORLDBOOK = [
    entry(1, "常驻角色摘要", C1, constant=True),
    entry(2, "角色基础", "角色基础：年龄十七，短发，常穿藏青外套，语速偏快。", keys=["林小满"]),
    entry(3, "角色别名", "角色别名：本名与简称两种写法指同一人，键表各占一列。", keys=["林小满", "小满"]),
    entry(4, "雨天场景", "阴天场景：路面反光，屋檐滴水，人物把外套领口立起来。",
          keys=["林小满"], secondary_keys=["下雨"], selective=True, logic="and_any",
          position="after_char"),
    entry(5, "雨伞与咖啡馆", "室内支线：门铃响两声，柜台后的人抬头看过来。",
          keys=["林小满"], secondary_keys=["雨伞", "咖啡馆"], selective=True, logic="and_all",
          position="after_char"),
    entry(6, "排除警察线", "支线排除项：窗口里没有反向二级键时，本条才进候选。",
          keys=["林小满"], secondary_keys=["警察"], selective=True, logic="not_any",
          position="after_char"),
    entry(7, "罗马字名", "拉丁转写条目：原文用大写，键表用小写，靠档位决定比较口径。",
          keys=["lin xiaoman"]),
    entry(8, "单字「雨」", "单字全词条目：只在开启全词匹配的档位里才可能与中文正文对上。",
          keys=["雨"], match_whole_words=True),
    entry(9, "咖啡馆·浅扫", "浅扫条目：只看最近一条消息，扫不到就退出候选。",
          keys=["咖啡馆"], position="at_depth", depth=1),
    entry(10, "咖啡馆·深扫", "深扫条目：回溯最近六条消息，命中窗口更宽。",
          keys=["咖啡馆"], position="at_depth", depth=6),
    entry(11, "英文词条", "英文条目：键为小写，原文首字母大写，考大小写口径。", keys=["starlight"]),
    entry(12, "递归源", "递归源条目：正文里写着「灯塔」两字，用来带出递归目标。", keys=["咖啡馆"]),
    entry(13, "递归目标", "递归目标条目：由上一层正文带出，窗口里没有它也会进候选。", keys=["灯塔"]),
    entry(14, "递归排除", "递归排除条目：只在直接命中时参与，递归轮次里被排除。",
          keys=["灯塔"], recursion_exclude=True),
    entry(15, "道具·高权重", "同组道具甲：权重一百，同组择一时胜出。",
          keys=["地图"], group="props", group_weight=100),
    entry(16, "道具·低权重", "同组道具乙：权重五十，同组择一时被甲挤掉。",
          keys=["地图"], group="props", group_weight=50),
    entry(17, "概率条目", "概率条目：命中后仍要过一次随机判定，判不过就不注入。",
          keys=["骰子"], probability=50),
    entry(18, "顺序·高", "顺序条目甲：order 两百，排在顺序条目乙之前。",
          keys=["林小满"], order=200),
    entry(19, "顺序·低", "顺序条目乙：order 十，排在顺序条目甲之后。",
          keys=["林小满"], order=10),
    entry(20, "超长常驻", C20, constant=True),
    entry(21, "尾声线索", "末轮线索条目：只在最后两条消息进窗时才可能命中。", keys=["尾声"]),
    entry(22, "停用条目", "停用条目：enabled 为假，任何档位都不许注入本条。",
          keys=["林小满"], enabled=False),
    entry(23, "空键选择性", "空键条目：主键列表为空，本基线判定为永不命中。",
          secondary_keys=["下雨"], selective=True, logic="and_any"),
    entry(24, "能力探针·正则键", "正则键探针：键串写成两个斜杠包住，本基线按字面串比较。",
          keys=["/地.图/"], capability_probe=True),
    entry(25, "能力探针·正则内容", "内容宏探针：{{roll:d6}} 与 {{user}} 原样保留，不做替换。",
          keys=["骰子"], capability_probe=True),
]

# role, text；下标即 chat.jsonl 的 i。
CHAT = [
    ("system", "你是角色扮演引擎。当前场景含角色：林小满。"),
    ("user", "外面下雨了，我没带伞。"),
    ("assistant", "我撑着雨伞走进咖啡馆，屋檐下有人在等。"),
    ("user", "Starlight 这个词我刚才见过。"),
    ("assistant", "我把地图折好塞进背包。"),
    ("user", "来掷一把骰子决定吧。"),
    ("assistant", "咖啡已经凉了，我重新煮一壶。"),
    ("user", "远处灯塔的光扫过海面。"),
    ("assistant", "我合上书，靠着栏杆。"),
    ("user", "故事快到尾声了。"),
    ("assistant", "街灯一盏一盏亮起来。"),
    ("user", "My name is LIN XIAOMAN."),
]

# §1.2 受控事实表，逐行照抄：i / role / 必须包含。
CONTROLLED = [
    (0, "system", "林小满"),
    (1, "user", "下雨"),
    (2, "assistant", "雨伞"),
    (2, "assistant", "咖啡馆"),
    (3, "user", "Starlight"),
    (4, "assistant", "地图"),
    (5, "user", "骰子"),
    (6, "assistant", "咖啡"),
    (7, "user", "灯塔"),
    (8, "assistant", "书"),
    (9, "user", "尾声"),
    (10, "assistant", "灯"),
    (11, "user", "LIN XIAOMAN"),
]

PROFILES = [
    ("P0", "默认", 4, True, 4000, False, False, "主读数（改后/方案）"),
    ("P1", "关递归", 4, False, 4000, False, False, "消融对：recursive"),
    ("P2", "浅扫", 1, True, 4000, False, False, "消融对：scan_depth"),
    ("P3", "紧预算", 4, True, 600, False, False, "消融对：budget（溢出策略）"),
    ("P4", "大小写＋全词", 4, True, 4000, True, True, "消融对：匹配口径"),
]

# 除 uid12 外，正文一律不含触发键（生成器自检）。
EXPECTED_CONTENT_HITS = {12: ["灯塔"]}


def build_profiles():
    rows = []
    for name, label, scan_depth, recursive, budget, cs, ww, purpose in PROFILES:
        rows.append({
            "name": name, "label": label, "scan_depth": scan_depth,
            "recursive": recursive, "recursive_max_depth": RECURSIVE_MAX_DEPTH,
            "budget_chars": budget, "case_sensitive": cs, "whole_words": ww,
            "seed": SEED, "purpose": purpose,
        })
    return {"schema": SCHEMA_PROFILES, "seed": SEED,
            "recursive_max_depth": RECURSIVE_MAX_DEPTH, "profiles": rows}


def build_worldbook():
    return {"schema": SCHEMA_WORLDBOOK, "entries": WORLDBOOK}


def build_chat():
    return [{"i": i, "role": role, "text": text} for i, (role, text) in enumerate(CHAT)]


def check(wb, chat, profiles):
    """逐条核对 §1.1/§1.2/§1.3；返回核对的条目数。"""
    n = 0
    ents = wb["entries"]
    uids = [e["uid"] for e in ents]
    assert uids == list(range(1, 26)), "uid 序列必须是 1..25"
    assert len(set(uids)) == 25, "uid 必须唯一"
    assert sum(1 for e in ents if e["capability_probe"]) == 2, "探针必须恰为 2 条"
    n += 3

    probes = {e["uid"] for e in ents if e["capability_probe"]}
    assert probes == {24, 25}, "探针 uid 必须是 24/25"
    n += 1

    for e in ents:
        assert set(e) == {
            "uid", "comment", "content", "keys", "secondary_keys", "selective",
            "selective_logic", "enabled", "constant", "order", "position", "depth",
            "probability", "case_sensitive", "match_whole_words", "group",
            "group_weight", "recursion", "capability_probe"}, "字段集必须等于 §3.1"
        assert set(e["recursion"]) == {"exclude", "prevent", "delay"}
        assert e["selective_logic"] in ("and_any", "and_all", "not_any")
        assert e["position"] in ("before_char", "after_char", "at_depth")
        assert e["probability"] == (50 if e["uid"] == 17 else 100), "仅 uid17 概率 50"
        n += 5

    # 正文触发键：只允许 uid12 含「灯塔」。
    keys_lower = [k.lower() for e in ents for k in e["keys"] if not k.startswith("/")]
    for e in ents:
        hits = sorted({k for k in keys_lower if k in e["content"].lower()})
        assert hits == EXPECTED_CONTENT_HITS.get(e["uid"], []), \
            "uid{} 正文触发键不符：{}".format(e["uid"], hits)
        n += 1

    assert len(C20) == 900, "uid20 正文必须 900 字符，实为 %d" % len(C20)
    assert (len(C1), len(C1.encode("utf-8"))) == (56, 168), "uid1 正文必须 56 字符 / 168 字节"
    assert sum(1 for e in ents if e["constant"]) == 2, "常驻条目必须 2 条（uid1/20）"
    assert sum(1 for e in ents if not e["enabled"]) == 1, "停用条目必须 1 条（uid22）"
    assert len({e["uid"] for e in ents if e["group"] == "props"}) == 2, "props 组 2 条"
    n += 4

    # §1.2 对话与受控事实。
    assert len(chat) == 12, "对话必须 12 条"
    n += 1
    for i, row in enumerate(chat):
        assert row["i"] == i, "i 必须 0..11 连续"
        assert row["role"] in ("system", "user", "assistant")
        n += 2
    for i, role, must in CONTROLLED:
        assert chat[i]["role"] == role, "i=%d role 不符：%s" % (i, chat[i]["role"])
        assert must in chat[i]["text"], "i=%d 缺受控子串 %s" % (i, must)
        n += 2

    # 评估轮：turn k 喂前 2k 条。
    for k in range(1, 7):
        assert len(chat[:2 * k]) == 2 * k
        n += 1

    # §1.3 设置档逐字核对。
    got = {(p["name"], p["scan_depth"], p["recursive"], p["budget_chars"],
            p["case_sensitive"], p["whole_words"]) for p in profiles["profiles"]}
    want = {(name, sd, rec, bud, cs, ww)
            for name, _label, sd, rec, bud, cs, ww, _p in PROFILES}
    assert got == want, "设置档与 §1.3 不符"
    assert [p["name"] for p in profiles["profiles"]] == ["P0", "P1", "P2", "P3", "P4"]
    assert profiles["recursive_max_depth"] == 3, "recursive_max_depth 必须 3"
    n += 3
    return n


def dumps_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def dumps_jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    wb = build_worldbook()
    chat = build_chat()
    profiles = build_profiles()
    checks = check(wb, chat, profiles)

    files = [
        (DATA / "worldbook.json", dumps_json(wb)),
        (DATA / "chat.jsonl", dumps_jsonl(chat)),
        (DATA / "profiles.json", dumps_json(profiles)),
    ]
    print("FIXTURE schema=%s entries=%d chat=%d profiles=%d checks=%d"
          % (SCHEMA_WORLDBOOK, len(wb["entries"]), len(chat), len(profiles["profiles"]), checks))
    for e in wb["entries"]:
        print("ENTRY uid=%d keys=%d sel=%s const=%s enabled=%s pos=%s depth=%s "
              "order=%d prob=%d chars=%d bytes=%d probe=%s"
              % (e["uid"], len(e["keys"]), int(e["selective"]), int(e["constant"]),
                 int(e["enabled"]), e["position"], "null" if e["depth"] is None else e["depth"],
                 e["order"], e["probability"], len(e["content"]),
                 len(e["content"].encode("utf-8")), int(e["capability_probe"])))
    for path, text in files:
        digest = write_text(path, text)
        print("SHA %s file=%s" % (digest, path.relative_to(ROOT).as_posix()))
    print("OK checks=%d" % checks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
