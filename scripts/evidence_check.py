# -*- coding: utf-8 -*-
"""灵枢插件测评 · 证据链校验件（纯 Python 标准库；**不触网、零第三方依赖**）。

它回答两个问题：

    ① **「review/data/plugins.json 里引用的公开文档原文，是不是真的长那样？」**
       引文快照（review/evidence/*） ←→ 快照清单（review/evidence/manifest.json）
                                     ←→ 测评数据里的 claim（review/data/plugins.json）
    ② **「那些标了『本机复跑』的原始输出，现在还跑得出来吗？」**
       逐条跑 `scripts/evidence_probe.py` 的具名探针，与证据里的 `output` **逐字节比对**。

做法（全部离线）：

    ① 完整性：每个快照的 sha256 **与字节数**都与清单声明一致；清单条目的
       kind／source_url／fetched_at 也逐项校验；**反向遍历**——目录里存在但清单没登记的
       快照同样点名（早先版本只看清单，多出来的文件永远不可见）。
    ② 出处明确：每条 evidence 都写清 `doc`（引文出自哪个快照），且该 doc 在清单里。
    ③ 引文忠实：每条 evidence 声明的 `quotes` **逐字**出现在该快照里，且不短于
       `MIN_QUOTE_LEN` 字符（`'遗忘'`、`'99.2'` 这类短串在十万字节文档里几乎必然命中，
       属无信息量引文）。
    ④ 复算：`kind == "本机复跑"` 的证据，其 `output` 必须与探针 stdout **逐字节相同**。
       这是「可复跑证据」第一次有了机器判据——差一个字节就点名判红。

为什么这样能当「可复跑证据」：本机直连 github.com 在部分环境不可用，但快照与哈希一起入库后，
**第三方无需联网**即可核对「我们引用的到底是哪一份文档、引用的那几句话是否逐字在文档里」；
而「本机复跑」那一档更进一步——**现在再跑一遍探针，读数必须一字不差**。

**边界（如实声明）**：①②③ 证明的是「本仓这份快照自洽 ＋ 引文忠实」，
**不等于**「这份快照与上游文档逐字节相同」（上游字节未在离线条件下取指纹）；
④ 证明的是「探针现在仍产出这段输出」，**不等于**「被测评插件的运行时行为如此」。

用法：
    python -X utf8 scripts/evidence_check.py            # 默认含复算；退出码 0 = 全部一致
    python -X utf8 scripts/evidence_check.py --no-repro # 跳过复算（只查快照与引文）
    python -X utf8 scripts/evidence_check.py --quiet    # 静默：只输出 ODD <id> 行（供守卫解析）
    python -X utf8 scripts/evidence_check.py --json     # 以 JSON 打印对账表（机器可读）

退出码：0 = 全部一致；1 = 检出不一致（逐条点名）；2 = 输入/环境错误（fail-closed）。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE_DIR = os.path.join(ROOT, "review", "evidence")
MANIFEST = os.path.join(EVIDENCE_DIR, "manifest.json")
PLUGINS = os.path.join(ROOT, "review", "data", "plugins.json")
PROBE_SCRIPT = os.path.join(ROOT, "scripts", "evidence_probe.py")

#: 清单条目的必填字段（`file` 另有专项判据）。
MANIFEST_FIELDS = ("kind", "source_url", "sha256", "bytes", "fetched_at")

#: 允许的快照种类。
SNAPSHOT_KINDS = ("README", "VERSION", "RUN")

#: 引文最小长度——与 `scripts/review_build.py` 的 `MIN_QUOTE_LEN` 同口径，两处都判（纵深防御）。
MIN_QUOTE_LEN = 6

#: 本机复跑的类型名（与 review_build.EVIDENCE_KINDS 对齐）。
KIND_LOCAL = "本机复跑"


# 生效条件：path 为任意文件路径时返回其 sha256（十六进制小写）；读不到则抛 OSError。
def sha256_file(path) -> str:
    """文件 sha256（流式读，避免整份文档进内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# 生效条件：path 为 JSON 文件路径时返回其对象；读取或解析失败抛 ValueError（由 main 收成 fail-closed）。
def load_json(path):
    """读一个 JSON 文件（不触网）。"""
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError("读取失败：%s（%s）" % (path, exc))


#: 严格日期**形状**（与 `review_build.py:80` 的 `DATE_RE` 同款）。
#: ★本笔：`review_build` 与 `evidence_check` 各有一个同名同述的 `date_ok`，**已实际分叉**：
#: `evidence_check` 旧实现只做「`datetime.date.fromisoformat` 可解析 ＋ `len(s) == 10`」，
#: 而 **Python 3.11+ 的 `fromisoformat` 接受 ISO 周日期** —— `"2026-W01-1"` 恰好 10 字符、
#: 且能被解析（⇒ `2025-12-29`）⇒ 旧实现判 **True**，而 `review_build` 判 **False**。
#: 本函数 docstring 自称「形状 ＋ 日历双判」，旧实现根本没有形状判据（长度 ≠ 形状）。
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


# 生效条件：text 为任意值时返回其是否为真实存在的 YYYY-MM-DD（形状 ＋ 日历双判）。
def date_ok(text) -> bool:
    """日期校验：形状 ＋ 日历。

    ★本笔：补上**形状**那一半（旧实现只有「可解析 ＋ 长度 10」）。与
    `review_build.date_ok` 的判据逐位一致（同款 `DATE_RE.fullmatch` ＋
    `fromisoformat`）——两处同名同述的实现不得分叉。
    """
    s = str(text or "")
    if not DATE_RE.fullmatch(s):
        return False
    try:
        datetime.date.fromisoformat(s)
    except ValueError:
        return False
    return True


# 生效条件：doc 为快照清单对象时返回「文件名 → 清单项」映射；结构不符抛 ValueError。
def manifest_index(manifest) -> dict:
    """快照清单 → {file: 清单项}。"""
    docs = manifest.get("documents") if isinstance(manifest, dict) else None
    if not isinstance(docs, list) or not docs:
        raise ValueError("快照清单结构不符（须含非空 documents 数组）：%s" % MANIFEST)
    out = {}
    for d in docs:
        if not isinstance(d, dict) or not str(d.get("file") or ""):
            raise ValueError("快照清单有条目缺 file：%r" % (d,))
        out[str(d["file"])] = d
    return out


# 生效条件：无必需形参时返回 (探针模块, 错误串)——import 失败时模块为 None 且错误串非空（fail-closed）。
def load_probe_module():
    """动态载入探针模块（保持本件与探针文件解耦：不靠包结构，只看同仓路径）。"""
    if not os.path.isfile(PROBE_SCRIPT):
        return None, "找不到探针脚本：%s" % PROBE_SCRIPT
    try:
        spec = importlib.util.spec_from_file_location("evidence_probe_for_check", PROBE_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:                       # noqa: BLE001 —— 载入期任何异常都收成 fail-closed
        return None, "探针模块载入失败：%s" % exc
    if not hasattr(mod, "render"):
        return None, "探针模块缺 render()：%s" % PROBE_SCRIPT
    return mod, ""


# 生效条件：root 为其实现副本所在仓根、want_repro 为真时逐条核对
# 「快照哈希与字节 / 清单字段 / 反向遍历 / 出处明确 / 引文忠实 / 本机复跑逐字节复算」，
# 返回 (对账行列表, 不一致行列表)。
def audit(root=None, want_repro=True) -> tuple:
    """证据链对账；返回 (rows, bad)。"""
    base = root or ROOT
    ev_dir = os.path.join(base, "review", "evidence")
    manifest = load_json(os.path.join(ev_dir, "manifest.json"))
    index = manifest_index(manifest)
    data = load_json(os.path.join(base, "review", "data", "plugins.json"))
    recs = data.get("records")
    if not isinstance(recs, list):
        raise ValueError("测评数据结构不符（须含 records 数组）：%s" % PLUGINS)

    rows, bad = [], []

    # ① 快照完整性（哈希 ＋ 字节 ＋ 清单字段）
    for name in sorted(index):
        p = os.path.join(ev_dir, name)
        item = index[name]
        want = str(item.get("sha256") or "")
        if not os.path.isfile(p):
            bad.append("快照缺失：%s" % name)
            continue
        got = sha256_file(p)
        got_bytes = os.path.getsize(p)
        ok = (got == want)
        rows.append({"kind": "snapshot", "id": name, "ok": ok,
                     "detail": "sha256 %s" % ("一致" if ok else "不一致"),
                     "want": want, "got": got})
        if not ok:
            bad.append("快照哈希不符：%s（清单 %s…／实得 %s…）"
                       % (name, want[:12], got[:12]))
        # 字节数：清单里写了就必须对得上——它是「这份快照没被换过」的第二道旁证。
        try:
            want_bytes = int(item.get("bytes"))
        except (TypeError, ValueError):
            bad.append("清单条目 %s 的 bytes 不是整数：%r" % (name, item.get("bytes")))
        else:
            if want_bytes != got_bytes:
                bad.append("快照字节数不符：%s（清单 %d ／ 实得 %d）"
                           % (name, want_bytes, got_bytes))
        # 清单字段：缺一即点名（早先版本对 kind／source_url／fetched_at 零校验）。
        for k in MANIFEST_FIELDS:
            if not str(item.get(k) or "").strip():
                bad.append("清单条目 %s 缺字段 %s" % (name, k))
        if str(item.get("kind") or "") not in SNAPSHOT_KINDS:
            bad.append("清单条目 %s 的 kind 非法：%r（须 %s 之一）"
                       % (name, item.get("kind"), "／".join(SNAPSHOT_KINDS)))
        src = str(item.get("source_url") or "")
        if src and not src.startswith(("http://", "https://")):
            bad.append("清单条目 %s 的 source_url 不是 http(s) URL：%r" % (name, src))
        if item.get("fetched_at") and not date_ok(item.get("fetched_at")):
            bad.append("清单条目 %s 的 fetched_at 不是真实日期：%r"
                       % (name, item.get("fetched_at")))

    # ①b **反向遍历**：目录里的快照必须在清单里登记（早先版本看不见「多出来的文件」）。
    on_disk = sorted(n for n in os.listdir(ev_dir)
                     if os.path.isfile(os.path.join(ev_dir, n)) and n != "manifest.json")
    for name in on_disk:
        if name not in index:
            bad.append("快照未登记：review/evidence/%s 不在 manifest.json 里"
                       "（多出来的文件必须点名，否则「清单齐全」是假的安全感）" % name)
    unlisted = [n for n in on_disk if n not in index]
    rows.append({"kind": "reverse", "id": "目录反向遍历",
                 "ok": not unlisted,
                 "detail": "%d 份在盘／%d 份在清单%s"
                           % (len(on_disk), len(index),
                              "" if not unlisted else "（未登记：%s）" % "，".join(unlisted))})

    # ② 出处明确 + ③ 引文忠实
    cache = {}
    for rec in recs:
        slug = str(rec.get("slug") or "?")
        for i, e in enumerate(rec.get("evidence") or []):
            eid = "%s#%d" % (slug, i)
            doc = str(e.get("doc") or "")
            if not doc:
                bad.append("出处未声明：%s 没写 doc（引文出自哪个快照）" % eid)
                rows.append({"kind": "cite", "id": eid, "ok": False,
                             "detail": "缺 doc 字段"})
                continue
            if doc not in index:
                bad.append("出处不在清单：%s 写的 doc=%r 不在 manifest.json" % (eid, doc))
                rows.append({"kind": "cite", "id": eid, "ok": False,
                             "detail": "doc=%s 不在清单" % doc})
                continue
            text = cache.get(doc)
            if text is None:
                # **严格解码**：早先用 errors="replace"，会把「这份快照根本不是 UTF-8」
                # 静默变形成替换字符，于是引文判据在一个已损坏的输入上给出「通过」。
                try:
                    with io.open(os.path.join(ev_dir, doc), encoding="utf-8") as fh:
                        text = fh.read()
                except (OSError, UnicodeDecodeError) as exc:
                    bad.append("快照不可读或不是 UTF-8：%s（%s）" % (doc, exc))
                    rows.append({"kind": "cite", "id": eid, "ok": False,
                                 "detail": "快照解码失败"})
                    cache[doc] = ""
                    continue
                cache[doc] = text
            quotes = e.get("quotes") or []
            if not isinstance(quotes, list) or not quotes:
                bad.append("引文未声明：%s 没写 quotes（从快照里摘了哪些话）" % eid)
                rows.append({"kind": "quote", "id": eid, "ok": False,
                             "detail": "缺 quotes"})
                continue
            weak = [q for q in quotes if len(str(q).strip()) < MIN_QUOTE_LEN]
            miss = [q for q in quotes if str(q) not in text]
            ok = not miss and not weak
            rows.append({"kind": "quote", "id": eid, "ok": ok,
                         "detail": "引文 %d 条%s%s"
                                   % (len(quotes),
                                      "逐字命中" if not miss else "有未命中",
                                      "" if not weak else "／%d 条过短" % len(weak))})
            if miss:
                bad.append("引文不忠实：%s 有 %d/%d 条在 %s 里找不到 —— %r"
                           % (eid, len(miss), len(quotes), doc, str(miss[0])[:60]))
            if weak:
                bad.append("引文过短（< %d 字符）：%s 有 %d 条 —— %r"
                           % (MIN_QUOTE_LEN, eid, len(weak), str(weak[0])[:40]))

    # ④ 本机复跑逐字节复算（可复跑证据的机器判据）
    if want_repro:
        mod, why = load_probe_module()
        if mod is None:
            bad.append("复算不可用：%s" % why)
            rows.append({"kind": "repro", "id": "探针载入", "ok": False, "detail": why})
        else:
            n_local = 0
            for rec in recs:
                slug = str(rec.get("slug") or "?")
                for i, e in enumerate(rec.get("evidence") or []):
                    if str(e.get("kind") or "") != KIND_LOCAL:
                        continue
                    n_local += 1
                    eid = "%s#%d" % (slug, i)
                    pid = str(e.get("probe") or "")
                    if not pid:
                        bad.append("复算缺探针：%s 标了「本机复跑」却没写 probe" % eid)
                        rows.append({"kind": "repro", "id": eid, "ok": False,
                                     "detail": "缺 probe"})
                        continue
                    try:
                        text, pok = mod.render(pid)
                    except ValueError as exc:
                        bad.append("复算失败：%s 的探针 %s 跑不起来（%s）" % (eid, pid, exc))
                        rows.append({"kind": "repro", "id": eid, "ok": False,
                                     "detail": "探针 %s 报错" % pid})
                        continue
                    same = (text == str(e.get("output") or ""))
                    ok = same and pok
                    rows.append({"kind": "repro", "id": eid, "ok": ok,
                                 "detail": "探针 %s：%s%s"
                                           % (pid, "逐字节相同" if same else "与 output 不一致",
                                              "" if pok else "；探针自报 NG")})
                    if not same:
                        bad.append("复算不一致：%s 的 output 与探针 %s 的 stdout 不同"
                                   "（差一个字节也算不一致）" % (eid, pid))
                    if not pok:
                        bad.append("探针自报 NG：%s（探针 %s）" % (eid, pid))
            if n_local == 0:
                bad.append("没有任何「本机复跑」证据——验收标准要的是「命令 ＋ 原始输出」，"
                           "全部靠转引不算")
    return rows, bad


# 生效条件：argv 为命令行参数列表时执行三方对账并返回退出码——0 一致 / 1 不一致 / 2 输入或环境错误。
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="灵枢插件测评 · 证据链校验件（纯 stdlib、不触网）")
    ap.add_argument("--quiet", action="store_true", help="只输出不一致行（ODD <id>）")
    ap.add_argument("--json", dest="as_json", action="store_true", help="以 JSON 打印对账表")
    ap.add_argument("--root", default="", help="仓根（默认本文件所在仓）")
    ap.add_argument("--no-repro", dest="no_repro", action="store_true",
                    help="跳过「本机复跑」逐字节复算（默认**会**复算）")
    ap.add_argument("--repro", dest="only_repro", action="store_true",
                    help="只做复算（等价于默认行为里那一段；与 --no-repro 互斥）")
    args = ap.parse_args(argv)
    if args.no_repro and args.only_repro:
        sys.stderr.write("[错误] `--repro` 与 `--no-repro` 互斥\n")
        return 2
    try:
        rows, bad = audit(args.root or None, want_repro=not args.no_repro)
    except ValueError as exc:
        sys.stderr.write("[错误] %s\n" % exc)
        return 2

    if args.as_json:
        sys.stdout.write(json.dumps({"rows": rows, "bad": bad},
                                    ensure_ascii=False, indent=2) + "\n")
    elif args.quiet:
        for b in bad:
            sys.stdout.write("ODD %s\n" % b)
    else:
        snap = [r for r in rows if r["kind"] == "snapshot"]
        other = [r for r in rows if r["kind"] in ("cite", "quote")]
        repro = [r for r in rows if r["kind"] == "repro"]
        rev = [r for r in rows if r["kind"] == "reverse"]
        print("证据链对账（快照 ←→ 清单 ←→ 测评数据 ←→ 本机复跑；全程不触网）")
        print("=" * 72)
        print("① 快照完整性（sha256 ＋ 字节数 ＋ 清单字段）")
        for r in snap:
            print("   [%s] %-34s %s" % ("OK" if r["ok"] else "NG", r["id"], r["detail"]))
        for r in rev:
            print("   [%s] %-34s %s" % ("OK" if r["ok"] else "NG", r["id"], r["detail"]))
        print("② / ③ 出处明确 + 引文忠实（含最短长度）")
        for r in other:
            print("   [%s] %-34s %s" % ("OK" if r["ok"] else "NG", r["id"], r["detail"]))
        if repro:
            print("④ 本机复跑逐字节复算（证据的 output 必须等于探针 stdout）")
            for r in repro:
                print("   [%s] %-34s %s" % ("OK" if r["ok"] else "NG", r["id"], r["detail"]))
        elif args.no_repro:
            print("④ 本机复跑复算：**已按 --no-repro 跳过**")
        print("=" * 72)
        print("快照 %d 份；引文条目 %d 条；复算 %d 条；不一致 %d 处"
              % (len(snap), len(other), len(repro), len(bad)))
        if bad:
            print("不一致明细：")
            for b in bad:
                print("   - %s" % b)
        else:
            print("全部一致：引用的每一句都在所声明的快照里逐字存在，"
                  "且每条「本机复跑」证据现在仍逐字节跑得出同一段输出。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
