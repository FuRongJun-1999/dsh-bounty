# -*- coding: utf-8 -*-
"""守卫：`scripts/review_build.py`（插件测评子站生成器）——断言 ＋ 定点变异自证。

对象：`scripts/review_build.py`（真源 → 静态子站的**纯函数 + 写盘**，零网络、纯 stdlib）。
真源：`review/data/plugins.json`；体例取自同仓 `tests/test_build_site.py`／`tests/test_bounty_list.py`。

为什么另立本件：本子站的成立前提是「**页面上的每个数字都能在真源里找到对应读数**」，
且「**没有读数的项被显式标注为未测、而不是被静默算成好成绩**」——这是**映射规则**，
不是渲染细节。故本件 = ①逐条正反断言（真源 → 榜单／详情／方法页的每条映射）
＋ ②每条映射一个**定点变异**（把该映射短路 ⇒ 对应断言**必然转红**且**恰好**转红；
多红＝断言语义纠缠，少红＝判据空转）。

断言组：
  [A] 真源面：条数下限 / 五维齐备 / 值域 / 证据三项齐 / 必填非空 / 版本可锚 / slug 唯一
  [B] 站点面：文件集 / 页数 / 榜单次序 / 总分＝五维求和 / 详情证据块 / 边界 / 未测条款 / 口径标注
  [Q] 安全与确定性：HTML 转义 / 注入被转义 / 逐字节一致 / 零第三方 import / fail-closed 不落盘

用法：
  python -X utf8 tests/test_review_build.py            # 正向：全部断言，末行「通过 N / 失败 M」
  python -X utf8 tests/test_review_build.py --quiet    # 只输出 `RED <id>`（供变异自证解析）
  python -X utf8 tests/test_review_build.py --mutate   # 定点变异自证（逐条须恰好命中期望红项）
  python -X utf8 tests/test_review_build.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中；1 = 有断言失败 / 变异未按预期转红；
        2 = ANCHOR-MISS（锚点在实现里命中次数 ≠1——实现漂移即硬失败）。

★ 沙箱根怎么选（**探针 ＋ 回退**）：先试 `tempfile.mkdtemp()`（与上游
  `tests/test_bounty_board.py` 同体例），**失败才**回退到仓根**外**的
  `.review_guard_tmp/`（按序号建目录）。为什么需要回退：本机 DSH 文件沙箱下连系统临时目录
  也不可写（`WinError 5`），而仓根父目录可写。
  两处如实声明：①回退路径落在**仓根之外**（父目录只读的环境下它会失败——那时会给出点名错误，
  而不是栈回溯）；②`REVIEW_SCRATCH_ROOT` 可由外部指定，此时清理权不归本进程。
"""
from __future__ import annotations

import atexit
import html
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid

#: 本件会在仓内 `sys.path.insert(0, scripts/)` 后 import 生成器——不许因此落下 `__pycache__`
#: （那会让 `git status` 变脏，也让「补丁全为新增」这条边界声明不成立）。
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))          # <仓根>/tests
ROOT = os.path.dirname(HERE)                               # <仓根>
GEN_REL = "scripts/review_build.py"
DATA_REL = "review/data/plugins.json"
OUT_REL = "review/site"
GUARD_REL = "tests/test_review_build.py"
CI_REL = ".github/workflows/review-check.yml"

#: **被测实现的确切路径**（本守卫旁边那一份）。
#: 所有探针都必须读它——包括在沙箱副本里重跑本守卫的情形（那时 ROOT 会指向沙箱，
#: 于是一定读到**变异后的那一份**）。早期版本让探针改读某个子孙沙箱里的副本，
#: 而那份副本取自**变异前**的源码，于是 Q1/A10–A13 在变异下不会红——判据空转。
GEN_PATH = os.path.join(ROOT, *GEN_REL.split("/"))
GEN_DIR = os.path.dirname(GEN_PATH)

#: **已提交面**：交付仓里那份真源与产物。
#: 不能简单用 `dirname(ROOT)`——定点变异会把**本守卫文件**复制进沙箱，
#: 那时 `__file__` 指向沙箱，`ROOT` 也是沙箱，祖先里根本没有已提交的产物。
#: 故按「哪个祖先目录同时含有 review/site 与 review/data/plugins.json」来定位：
#: 正常跑命中仓根自身；变异跑会往上命中真交付仓（沙箱是它的子孙）。
def _locate_committed_root():
    """找到**含已提交产物**的仓根。

    优先级：
      ① 环境变量 `REVIEW_COMMITTED_ROOT`——变异自证时由 `_run_quiet` 显式传**真交付仓**，
         这是唯一可靠的办法：沙箱与它上层的临时目录都可能"看起来像"仓根。
      ② 否则从 `ROOT` 往上找第一个「有真源 ＋ 有至少一页 .html」的祖先。
    判据必须要求**至少一页 .html**：只看 `review/site` 目录是否存在会截停在空目录上
    （变异沙箱的 review/site 就是空的），于是 C7/C8 在每个变异体上假红（实测踩过）。
    """
    env_root = os.environ.get("REVIEW_COMMITTED_ROOT")
    if env_root and os.path.isfile(os.path.join(env_root, *DATA_REL.split("/"))):
        return os.path.abspath(env_root)
    cur = os.path.abspath(ROOT)
    for _ in range(6):
        data_ok = os.path.isfile(os.path.join(cur, *DATA_REL.split("/")))
        site = os.path.join(cur, *OUT_REL.split("/"))
        pages_ok = os.path.isdir(site) and any(
            n.endswith(".html") for n in os.listdir(site))
        if data_ok and pages_ok:
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.abspath(ROOT)


REAL_ROOT = _locate_committed_root()
#: 已提交真源的路径。**允许被环境变量覆盖**——变异自证会把 `REVIEW_DATA_SRC` 指向一份
#: **临时副本**，于是数据面变异永远不会写到已提交的真源上。
#: 这一点是硬要求：早先让变异直接改已提交真源，一次硬杀进程（`os._exit`）就把它改脏了，
#: 之后所有运行都红——交付物被自己的自证过程破坏，比不测更糟。
#: 默认（正常跑）仍指向已提交真源，故 [C] 组判的始终是「已提交的真源 ↔ 已提交的产物」。
DATA_SRC = os.environ.get("REVIEW_DATA_SRC") or os.path.join(
    REAL_ROOT, *DATA_REL.split("/"))
SITE_SRC = os.path.join(REAL_ROOT, *OUT_REL.split("/"))

QUIET = "--quiet" in sys.argv
_red = []
#: 实跑断言计数（末行 N 的来源；`--quiet` 也会回报给父进程）。
_RUN = [0]

#: 守卫侧**独立声明**（不 import 被守卫对象——否则同错同绿，判据一起空转）。
DIMENSIONS = ("检索质量", "记忆持久", "注入预算", "隐私与本地性", "可验证性")
DIM_MIN, DIM_MAX = 1, 5
MIN_PLUGINS = 3
MIN_PAGES = 4
BASE_PAGES = ("index.html", "board.html", "method.html")
#: 标准库 import 白名单。三条纯 stdlib 件**共用**它（生成器 / 探针 / 证据链校验件）——
#: 早先版本只扫生成器，探针与校验件的 import 面零覆盖。
#: `__import__(` / `importlib` 另由 Q4 的文本判据禁掉：`__import__("requests")` 能绕过
#: 「`^\s*(?:import|from)`」这种行首正则（早先版本的变异自己就用过 `__import__("datetime")`，
#: 等于自证了这个绕过面）。
ALLOWED_IMPORTS = {"__future__", "argparse", "datetime", "hashlib", "html",
                   "importlib", "io", "json", "os", "re", "sys"}

#: 注入夹具：放进**会被页面渲染**的字段（插件名）——用来证转义是活的。
INJECT_NAME = 'eve<img src=x onerror=alert(1)>'


def ok(name, cond, detail=""):
    """逐条记账：静默模式下只吐 `RED <id>`（供变异自证解析）。"""
    #: **实跑计数**：末行的 N 由它给出，不再手写常数——手写常数一旦漂移，
    #: 或某组判据中途提前 `return`（少跑几条），末行读数就会骗人。
    _RUN[0] += 1
    if not cond:
        _red.append(name.split(" ")[0])
    if QUIET:
        return
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                           "" if cond or not detail else "  · %s" % detail))


# ================================================================ 沙箱（每次运行一个全新目录）
#: 沙箱根：落在工作区里（不是系统临时目录——见文件头沙箱注记）。**每个沙箱一个全新目录**，
#: 目录名带本次进程的随机令牌：Windows 会在删掉目录后把安全描述符留在父目录里，
#: 重建同名目录会把旧的拒绝项一并恢复，于是新目录又不可写（本机沙箱实测）。
#: 故一律用「从未出现过」的名字，且**不嵌套**（每个沙箱都是自己的仓根，与上游
#: `tests/test_build_site.py` 的「仓根沙箱」体例一致）。`uuid` 属标准库，不违反零依赖。
# 生效条件：无必需形参时返回一个可写的沙箱根——**先试 `tempfile.mkdtemp()`，失败才回退**。
# 为什么要有回退：本机 DSH 文件沙箱下连系统临时目录也不可写（`WinError 5`），
# 而仓根父目录可写。回退路径落在**仓根之外**；父目录也只读时给出**点名错误**而不是栈回溯
# （早先版本直接 `os.makedirs`，父目录只读会抛未捕获异常，末行「通过 N / 失败 0」根本不打印）。
def _pick_scratch_root():
    env = os.environ.get("REVIEW_SCRATCH_ROOT")
    if env:
        return env
    cand = ""
    try:
        cand = tempfile.mkdtemp(prefix="review_guard_")
        # **必须真写一次**才算探到：本机沙箱下 `mkdtemp()` 能建出目录，但目录**内**不可写
        # （`WinError 5`）。只看 mkdtemp 是否抛异常会把「不可写的临时目录」当可用。
        probe = os.path.join(cand, "write_probe")
        os.makedirs(os.path.join(probe, "x"), exist_ok=True)
        shutil.rmtree(probe, ignore_errors=True)
        return cand
    except OSError as exc:
        if cand:
            shutil.rmtree(cand, ignore_errors=True)
        fallback = os.path.join(os.path.dirname(ROOT), ".review_guard_tmp")
        try:
            os.makedirs(fallback, exist_ok=True)
        except OSError as exc2:
            raise SystemExit(
                "[错误] 守卫找不到可写的沙箱根：系统临时目录探针失败（%s）；"
                "回退目录 %s 也建不出来（%s）。可用环境变量 REVIEW_SCRATCH_ROOT "
                "指定一个可写目录。" % (exc, fallback, exc2))
        return fallback


SCRATCH_ROOT = _pick_scratch_root()
#: 清理权归**创建者**：父进程建根、父进程清；子进程（变异体守卫）只是借住，
#: 绝不 `rmtree` 整根——否则会把父进程放在根下的临时真源一起删掉（实测报 FileNotFoundError）。
_SCRATCH_OWNER = not os.environ.get("REVIEW_SCRATCH_ROOT")
RUN_TOKEN = uuid.uuid4().hex[:12]
_SANDBOX_N = [0]


# 生效条件：无必需形参时返回一个**全新**的沙箱仓根——含 scripts/review_build.py 与 tests/test_review_build.py 的副本。
def make_sandbox(obj=None):
    """新建一个自包含的仓根沙箱；obj 非空时同时落一份真源。"""
    _SANDBOX_N[0] += 1
    root = os.path.join(SCRATCH_ROOT, "sb_%s_%d" % (RUN_TOKEN, _SANDBOX_N[0]))
    #: 沙箱要自带 CI 定义——B15 读它（它不在变异面上，故必须随沙箱复制，
    #: 否则每个变异体都会把 B15 一起拖红，污染红项集合）。
    for rel in (GEN_REL, GUARD_REL, CI_REL):
        src = os.path.join(ROOT, *rel.split("/"))
        if not os.path.isfile(src):
            continue
        dst = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)
    #: 真源要带上——[C] 交付面组读它。
    #: **产物目录（review/site）刻意不预置**：预置旧页会让「旧页清理」（B13）在每个变异体上假红。
    data_src = os.path.join(ROOT, *DATA_REL.split("/"))
    if os.path.isfile(data_src):
        ddst = os.path.join(root, *DATA_REL.split("/"))
        os.makedirs(os.path.dirname(ddst), exist_ok=True)
        shutil.copy(data_src, ddst)
    if obj is not None:
        write_data(root, obj)
    return root


# 生效条件：无必需形参时返回一个**全新**的临时目录（放数据面变异用的真源副本），位于 SCRATCH_ROOT 下。
def make_scratch_dir():
    """给数据面变异放**临时真源副本**用的目录。

    放在 SCRATCH_ROOT 下，靠 `_SCRATCH_OWNER` 保证子进程不会把它删掉；
    名字带本次进程随机令牌，不复用（见文件头沙箱注记）。
    """
    os.makedirs(SCRATCH_ROOT, exist_ok=True)
    _SANDBOX_N[0] += 1
    d = os.path.join(SCRATCH_ROOT, "mutdata_%s_%d" % (RUN_TOKEN, _SANDBOX_N[0]))
    os.makedirs(d)
    return d


# 生效条件：无必需形参时返回一个**带已提交产物**的专用沙箱：产物取自 SITE_SRC，真源取自 SITE_SRC 同仓的 DATA_SRC。
def make_delivery_sandbox():
    """交付面专用沙箱。

    关键：产物一律取自 `SITE_SRC`（= 交付仓里**已提交**的那份 review/site），
    真源取自 `DATA_SRC`（= 交付仓里那份 plugins.json）——两者都锚在 `REAL_ROOT`，
    **不随变异体变化**（变异体只改自己沙箱里的副本）。
    于是「已提交的真源 与 已提交的产物 对不对得上」才真的被判：
    变异体把真源改坏后，产物仍是已提交那份，C7/C8 必然发现不一致。
    （若从变异沙箱取产物，[C] 会在每个变异体上假红，因为变异沙箱里根本没生成过站。）
    """
    root = make_sandbox()
    # 产物一律取自**已提交面** SITE_SRC（REAL_ROOT 下的 review/site）——它不随变异体变化。
    # 真源由 `_judge_delivery` 直接读 DATA_SRC（也是已提交面）；
    # 数据面变异（S13/S14）改的就是 DATA_SRC，故「真源 vs 产物」的对账能被判。
    if os.path.isdir(SITE_SRC):
        sdst = os.path.join(root, *OUT_REL.split("/"))
        os.makedirs(sdst, exist_ok=True)
        for name in os.listdir(SITE_SRC):
            if name.endswith(".html"):
                shutil.copy(os.path.join(SITE_SRC, name), os.path.join(sdst, name))
    return root


# 生效条件：root 为沙箱仓根、obj 为可 JSON 化对象时，把真源落到该沙箱的 review/data/plugins.json。
def write_data(root, obj):
    p = os.path.join(root, *DATA_REL.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, indent=2))
    return p


# 生效条件：ret 为首个返回值时返回「全部页面文件名」列表（排序，便于逐字节比对）。
def _pages(root, out_rel=OUT_REL):
    d = os.path.join(root, *out_rel.split("/"))
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


# 生效条件：text 为页面集合时返回其拼接（逐字节确定性比对用）。
def _dump(root, out_rel=OUT_REL):
    d = os.path.join(root, *out_rel.split("/"))
    if not os.path.isdir(d):
        return ""
    return "".join(io.open(os.path.join(d, n), encoding="utf-8").read()
                   for n in sorted(os.listdir(d)))


# 生效条件：root 为沙箱仓根、*args 为命令行参数时以子进程真跑生成器（显式指向沙箱内真源与产物，UTF-8、超时 300s），返回 CompletedProcess。
def run_gen(root, *args):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, "-X", "utf8", os.path.join(root, *GEN_REL.split("/")),
         "--data", DATA_REL, "--out", OUT_REL, *args],
        cwd=root, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=300)


# 生效条件：无必需形参时读真源（仓内 review/data/plugins.json）并返回其文档对象。
def read_src():
    with io.open(os.path.join(ROOT, *DATA_REL.split("/")), encoding="utf-8") as fh:
        return json.load(fh)


# 生效条件：text 为任意值时返回其**渲染后**的形态（守卫侧独立实现，用于与页面比对真源文本）。
def _md(text):
    """守卫侧的 inline_md 等价物（先转义、再把 **粗体** 与 `代码` 渲染成标签）。"""
    out = html.escape(str(text), quote=True)
    out = re.sub(r"`([^`]+)`", lambda m: "<code>%s</code>" % m.group(1), out)
    out = re.sub(r"\*\*([^*]+)\*\*", lambda m: "<b>%s</b>" % m.group(1), out)
    return out


# 生效条件：无必需形参时返回一份可覆盖各映射面的真源夹具（三条记录；含一条注入文本，用来证转义是活的）。
def fixture_doc():
    def rec(slug, name, dims, ev, unmeasured="未测 ＋ 夹具：本条用于守卫，非真实测评。",
            version="1.2.3"):
        return {"name": name, "slug": slug, "version": version,
                # 版本面必须锚在**不可变引用**（tag／commit）：这是生成器的硬判据。
                "version_source": "https://example.invalid/%s/v%s/package.json" % (slug, version),
                "version_checked_at": "2026-10-13",
                "self_review": False,
                "source_url": "https://example.invalid/%s" % slug,
                "reviewed_at": "2026-10-13", "dimensions": dict(zip(DIMENSIONS, dims)),
                "unmeasured_dims": [k for k, v in zip(DIMENSIONS, dims) if v == 1],
                "evidence": ev, "conclusion": "结论：逐项指回读数。",
                "boundary": "不适用条件：仅在夹具条件下成立。",
                "unmeasured": unmeasured}
    # 证据必须标来源档位：`本机复跑` 要带 probe，`公开文档转引` 不许带。
    # 引文长度须 ≥ MIN_QUOTE_LEN（短串在长文档里几乎必然命中，属无信息量引文）。
    ev = lambda tag: [{"kind": "本机复跑", "probe": "fixture.%s" % tag,
                       "cmd": "python -X utf8 demo_%s.py" % tag,
                       "output": "输出 %s：读数 1" % tag,
                       "source": "本机复跑（夹具，非真实测评）",
                       "doc": "fixture.%s.md" % tag,
                       "quotes": ["夹具引文 %s" % tag]}]
    # 三个总分互不相同（15／17／11）——否则「关掉排序」时 `(0, name)` 仍可能与期望同序，
    # 判据就空转了。这是夹具的**必要条件**，不是凑数。
    return {"records": [
        rec("alpha", "Alpha", [5, 4, 3, 2, 1], ev("alpha")),
        rec("beta", "Beta", [4, 4, 4, 3, 2], ev("beta")),
        rec("gamma", "Gamma", [3, 3, 2, 2, 1], ev("gamma"), version="1.2.4"),
    ]}


# ================================================================ [A] 真源面

def group_source(doc):
    print("[A] 真源面（条数下限 / 五维齐备 / 值域 / 证据三项 / 必填非空 / 版本 / slug 唯一）")
    recs = doc["records"]
    ok("A1 count 插件数 ≥ %d（验收标准下限）" % MIN_PLUGINS,
       len(recs) >= MIN_PLUGINS, "实得 %d" % len(recs))
    ok("A2 dims 每条 dimensions 恰为五维且齐备",
       all(isinstance(d.get("dimensions"), dict)
           and set(d["dimensions"]) == set(DIMENSIONS) for d in recs))
    ok("A3 range 每条五维值均为 %d–%d 整数（越界即拒）" % (DIM_MIN, DIM_MAX),
       all(isinstance(v, int) and not isinstance(v, bool)
           and DIM_MIN <= v <= DIM_MAX
           for d in recs for v in d["dimensions"].values()))
    ok("A4 triple 每条 evidence 均含 cmd／output／source 三项且非空",
       all(e.get("cmd", "").strip() and e.get("output", "").strip()
           and e.get("source", "").strip()
           for d in recs for e in d.get("evidence") or []))
    ok("A5 evcnt 每条 evidence ≥1 条（可复跑证据下限）",
       all(len(d.get("evidence") or []) >= 1 for d in recs))
    ok("A6 text 每条 conclusion／boundary／unmeasured 均非空（未测项必须显式写）",
       all(d.get("conclusion", "").strip() and d.get("boundary", "").strip()
           and d.get("unmeasured", "").strip() for d in recs))
    ok("A7 ver 每条 version 含形如 1.2.3 的字面版本号",
       all(re.search(r"\d+\.\d+(?:\.\d+)?", str(d.get("version", ""))) for d in recs))
    ok("A8 slug slug 全清单唯一（详情页文件名不撞车）",
       len({d["slug"] for d in recs}) == len(recs))
    ok("A9 url 每条 source_url 为 http(s):// 开头",
       all(str(d.get("source_url", "")).startswith("http") for d in recs))
    # A10–A13 是**拒绝面**：把一条合法记录改坏一处，校验件必须**点名拒收**。
    # 这几条不建在数据形状上，而建在 `validate` 的行为上——判据才真的在判。
    ok("A10 rej-dim 维度越界（%d）⇒ 校验件点名拒收" % (DIM_MAX + 1),
       _rejects("dimensions", lambda r: r["dimensions"].__setitem__(DIMENSIONS[0], DIM_MAX + 1)),
       REJ_ERR[0])
    ok("A11 rej-ev 证据为空 ⇒ 校验件点名拒收（每条须 ≥1 条可复跑证据）",
       _rejects("evidence", lambda r: r.__setitem__("evidence", [])),
       REJ_ERR[0])
    ok("A12 rej-triple 证据缺 output ⇒ 校验件点名拒收（命令＋输出＋来源缺一不可）",
       _rejects("triple", lambda r: r["evidence"][0].__setitem__("output", "  ")),
       REJ_ERR[0])
    ok("A13 rej-count 记录数 < %d ⇒ 校验件点名拒收" % MIN_PLUGINS,
       _rejects("records", lambda _r: None, drop_to=MIN_PLUGINS - 1),
       REJ_ERR[0])
    # A14–A15：slug 是**文档名**（会拼进 detail_<slug>.html），故必须收口。
    #   A14 只证「路径类输入被拒」（防路径穿越）；A15 只证「怪名被拒」（白名单＋长度）。
    #   两条用的是**同一道** slug_ok 判据——同一道闸的两个侧面，故各自的反例也不重叠。
    ok("A14 rej-slug 路径类 slug（../../evil、a/b、..\\evil、空串）⇒ 校验件点名拒收",
       all(_rejects("slug-" + tag, lambda r, v=v: r.__setitem__("slug", v))
           for tag, v in (("traverse", "../../evil"), ("slash", "a/b"),
                          ("backslash", "..\\evil"), ("empty", ""))),
       REJ_ERR[0])
    ok("A15 rej-slug2 怪名 slug（Alpha、a_b、a.b、65 长、1 长）⇒ 校验件点名拒收",
       all(_rejects("slug2-" + tag, lambda r, v=v: r.__setitem__("slug", v))
           for tag, v in (("upper", "Alpha"), ("under", "a_b"),
                          ("dot", "a.b"), ("long", "a" * 65),
                          ("single", "a"))),
       REJ_ERR[0])
    # A16：证据链字段——doc（出处快照）与 quotes（逐字引文）是「可复跑证据」的可核验面，缺一即拒收。
    ok("A16 rej-chain 证据缺 doc／quotes 为空 ⇒ 校验件点名拒收（证据链字段必填）",
       all(_rejects("chain-" + tag, fn)
           for tag, fn in (("nodoc", lambda r: r["evidence"][0].pop("doc", None)),
                           ("noquotes", lambda r: r["evidence"][0].pop("quotes", None)),
                           ("emptyquotes", lambda r: r["evidence"][0].__setitem__("quotes", [])))),
       REJ_ERR[0])


# ================================================================ [B] 站点面

def group_site(doc, root):
    print("[B] 站点面（文件集 / 页数 / 榜单次序 / 总分求和 / 证据块 / 边界 / 未测条款 / 口径标注）")
    recs = doc["records"]
    expect = sorted(set(BASE_PAGES) | {"detail_%s.html" % d["slug"] for d in recs})
    names = _pages(root)
    ok("B1 rc0 生成器退出码 0（真源 → 子站落盘）", LAST_RC[0] == 0,
       "rc=%s err=%s" % (LAST_RC[0], LAST_ERR[0][-160:]))
    ok("B2 files 页面集合 == 首页/榜单/方法/每插件一页（无缺无多）", names == expect,
       "实得 %s" % names)
    ok("B3 pages 页数 ≥ %d（验收标准：≥4 页）" % MIN_PAGES, len(names) >= MIN_PAGES,
       "实得 %d" % len(names))

    # 次序与求和**各自**取期望：
    #   B4 只按规则重排原始五维（不经被守卫对象的 total_score），故「关掉求和」不会连带红 B4；
    #      而「关掉排序」令榜面退化成字典序 ≠ 总分序，故必红 B4（夹具三个总分互不相同）。
    #   B5 只看取值集合、不看顺序，故「关掉排序」不牵连 B5。
    # 两类突变分别推翻**不同**的期望形态，正是让每条判据各自可红的关键。
    def order_by_rule(items, score):
        return [d["name"] for d in sorted(items, key=lambda d: (-score(d), d["name"]))]

    want = order_by_rule(recs, lambda d: sum(d["dimensions"].values()))
    board = _read(root, "board.html")
    order = re.findall(r'<a href="detail_[^"]+">([^<]+)</a>', board)
    ok("B4 order 榜单次序 == 总分降序（同分按插件名升序）", order == want,
       "实得 %s 期望 %s" % (order, want))
    # B5 把榜面总分当取值集合比，不看顺序。
    got_totals = sorted(int(x) for x in re.findall(r"<td><b>(\d+)</b></td>", board))
    ok("B5 sum 榜面总分取值集合 == 五维求和取值集合（不读手写总分字段）",
       got_totals == sorted(sum(d["dimensions"].values()) for d in recs),
       "实得 %s" % got_totals)

    ev_ok, ev_detail = True, ""
    for d in recs:
        t = _read(root, "detail_%s.html" % d["slug"])
        for e in d["evidence"]:
            if not (e["cmd"] in t and e["output"] in t
                    and "① 复跑命令" in t and "② 原始输出" in t):
                ev_ok, ev_detail = False, d["slug"]
                break
    ok("B6 ev 详情页含每条证据的命令与原始输出（含①命令／②输出两节标题）",
       ev_ok, ev_detail)

    bnd_ok, bnd_detail = True, ""
    for d in recs:
        t = _read(root, "detail_%s.html" % d["slug"])
        # 真源文本走 inline_md（粗体／代码会被渲染），故按**渲染后**的形态比对；
        # 早期版本拿原始串直接比，一接真源就假红（真源含 ** 与反引号）。
        if not ("边界 · 不适用条件" in t and _md(d["boundary"]) in t
                and "未测项（未测 ＋ 原因）" in t and _md(d["unmeasured"]) in t):
            bnd_ok, bnd_detail = False, d["slug"]
            break
    ok("B7 bnd 详情页含每条记录的边界／不适用条件与未测项（两节都在）",
       bnd_ok, bnd_detail)
    meth = _read(root, "method.html")
    head = _const_probe(root, "UNMEASURED_HEAD")
    ok("B8 unm 方法页含未测项处理小节（标题取自实现常量，且正文含「未测 ＋ 原因」）",
       head and ("<h2>%s</h2>" % head) in meth and "未测 ＋ 原因" in meth,
       "标题=%r 在页=%s" % (head, ("<h2>%s</h2>" % head) in meth))
    ok("B9 note 口径标注在位（测评分与悬赏声誉分不是一个量）",
       "不是同一个量" in board and "不是同一个量" in meth)
    ok("B10 check --check 一致时 0 / 漂移时 1 且点名漂移文件", CHECK_OK[0], CHECK_ERR[0])
    ok("B11 print --print 只打印不落盘", PRINT_OK[0], PRINT_ERR[0])

    # B12：详情页文件名必须**由 slug 唯一决定**，且恰好每个 slug 一个——防 "两个 slug 撞同一文件名"。
    got_slugs = sorted(n[len("detail_"):-len(".html")]
                       for n in names if n.startswith("detail_") and n.endswith(".html"))
    ok("B12 slug 文件名 = 每个 slug 恰好一个详情页（无撞车、无缺页）",
       got_slugs == sorted(d["slug"] for d in recs),
       "实得 %s" % got_slugs)

    # B13：删插件后重新生成 ⇒ 旧页面必须被清掉（否则产物与真源不一致，而 --check 也发现不了）。
    stale_ok, stale_detail = STALE_OK[0], STALE_DETAIL[0]
    ok("B13 stale 真源删掉一条后重新生成 ⇒ 旧 detail_<slug>.html 被清理",
       stale_ok, stale_detail)

    # B14：产物目录里若存在不该有的页，--check 必须报出来（否则「一致」是假的安全感）。
    ok("B14 extra --check 能发现产物目录里多出来的页（旧 slug 残留）",
       EXTRA_OK[0], EXTRA_ERR[0])
    # B16：**破坏性清理**面——`--out` 指向含别的生成器页面的目录时，外来页只报不删。
    # 为什么单列一条：同仓 `scripts/build_site.py` 的默认输出目录也叫 `site`，两站固定页名重叠
    # （都有 index.html／board.html）。无差别删 `*.html` 会让 `--out site` 一声不响地删掉
    # `site/honor.html`、`site/rules.html`——那是把别人的产物毁了，上游没有任何防线。
    ok("B16 foreign 误指向别人的产物目录时，外来页**不被删**（只报不删）",
       FOREIGN_OK[0], FOREIGN_ERR[0])

    # B15 不在这里判——它要看仓**外**的交付说明（沙箱里的相对路径取不到），
    # 若放在本组，任何变异都会把它一起拖红（多红＝语义纠缠）。故移到 judge() 之外单独判。


# ================================================================ [Q] 安全与确定性

def group_quality(root):
    print("[Q] 安全与确定性（转义 / 注入 / 逐字节一致 / 零第三方 import / fail-closed 不落盘）")
    ok("Q1 esc HTML 转义覆盖 <、>、&、引号（输出逐字符钉死）",
       _esc_probe() == "&lt;a&gt;&amp;&quot;&#x27;&lt;/a&gt;",
       "实得 %r" % _esc_probe())

    # 注入面：另起一个沙箱，把注入串放进**会被渲染的字段**（插件名），真跑生成器后查产物。
    # 本条只断言「原始标签永不进页面」——**质量**契约（转义形态正确）由 Q1 单独锚在 esc() 上；
    # 两条判据各测一面，故互不牵连（关掉 esc 只红 Q1，不会顺手把 Q2 也拖红）。
    inj_doc = fixture_doc()
    inj_doc["records"][0]["name"] = INJECT_NAME
    inj_root = make_sandbox(inj_doc)
    run_gen(inj_root)
    bad = _read(inj_root, "board.html") + _read(inj_root, "detail_alpha.html")
    raw_absent = ("<img src=x onerror=alert(1)>" not in bad
                  and INJECT_NAME not in bad and "<script>" not in bad)
    ok("Q2 inj 注入的插件名进页面后原始标签不出现（页面不做注入）",
       raw_absent, "raw_absent=%s" % raw_absent)

    r2 = make_sandbox(fixture_doc())
    rcA = run_gen(r2)
    first = _dump(r2)
    rcB = run_gen(r2)
    second = _dump(r2)
    ok("Q3 det 同真源两次生成逐字节相同（不含生成时刻）",
       rcA.returncode == 0 and rcB.returncode == 0 and first == second and first != "")
    # Q4：零第三方依赖**与**「不许用动态 import 绕过白名单」。三条纯 stdlib 件一并扫。
    scanned = ("scripts/review_build.py", "scripts/evidence_probe.py", "scripts/evidence_check.py")
    imports, sneaky = set(), []
    for rel in scanned:
        p = os.path.join(ROOT, *rel.split("/"))
        if not os.path.isfile(p):
            continue
        src = io.open(p, encoding="utf-8").read()
        for name in re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", src, re.M):
            imports.add(name.split(".")[0])
        if "__import__(" in src:
            sneaky.append("%s 用了 __import__(" % rel)
    #: `importlib` 只在白名单里是给 `importlib.util.spec_from_file_location`（按路径载入同仓探针）用的，
    #: 它**不是**第三方依赖；但 `importlib.import_module("requests")` 会是绕过面，故一并禁字面量。
    for rel in scanned:
        p = os.path.join(ROOT, *rel.split("/"))
        if os.path.isfile(p) and "import_module(" in io.open(p, encoding="utf-8").read():
            sneaky.append("%s 用了 import_module(" % rel)
    ok("Q4 deps 三条纯 stdlib 件零第三方依赖（import 落在白名单内，且禁用动态 import 绕过）",
       imports <= ALLOWED_IMPORTS and not sneaky,
       "多出 %s；绕过 %s" % (sorted(imports - ALLOWED_IMPORTS), sneaky))
    ok("Q5 fc fail-closed：真源非法 ⇒ 退出码 2 且点名、不落盘",
       FC_OK[0], FC_ERR[0])
    ok("Q6 unm 每条详情页含「未测」节（未测项不许静默省略）",
       all("未测" in _read(root, "detail_%s.html" % d["slug"])
           for d in fixture_doc()["records"]))
    # Q7：inline_md 的「先转义后替换」——这条安全声明原先零覆盖（改坏它没有任何断言会红）。
    # 输入同时区分两种坏法：没转义 → `<b><b>x</b></b>`；顺序反了 → `&lt;b&gt;&lt;b&gt;x&lt;/b&gt;&lt;/b&gt;`。
    got = _call_probe("inline_md", "'<b>**x**</b>'")
    ok("Q7 md inline_md 先转义后渲染（<b>**x**</b> ⇒ 转义标签 ＋ 真粗体）",
       got == "&lt;b&gt;<b>x</b>&lt;/b&gt;", "实得 %r" % got)
    # Q8：确定性不能只看「两次生成相同」——同秒内的秒级时间戳也能相同。直接判产物里没有时刻。
    page_txt = _read(root, "board.html") + _read(root, "index.html")
    ok("Q8 clock 产物里不含生成时刻（HH:MM 形态）",
       not re.search(r"\d{2}:\d{2}", page_txt))


# ---------------------------------------------------------------- 探针（子进程侧读一次即可）

LAST_RC = [None]
LAST_ERR = [""]
CHECK_OK = [False]
CHECK_ERR = [""]
PRINT_OK = [False]
PRINT_ERR = [""]
FC_OK = [False]
FC_ERR = [""]
REJ_ERR = [""]
_ESC = [""]
_CONSTS = {}
STALE_OK = [False]
STALE_DETAIL = [""]
EXTRA_OK = [False]
EXTRA_ERR = [""]
FOREIGN_OK = [False]
FOREIGN_ERR = [""]


def _read(root, name):
    p = os.path.join(root, *OUT_REL.split("/"), name)
    return io.open(p, encoding="utf-8").read() if os.path.isfile(p) else ""


# 生效条件：无必需形参时**从 GEN_PATH（被测实现本身）**跑 esc() 并返回其输出——变异下必随实现转红。
def _esc_probe():
    if _ESC[0]:
        return _ESC[0]
    code = ("import sys;sys.path.insert(0, %r);"
            "import review_build as rb;"
            "sys.stdout.write(rb.esc('<a>&\"\\'</a>'))" % GEN_DIR)
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONUTF8="1",
                                                  PYTHONDONTWRITEBYTECODE="1"),
                       timeout=120)
    _ESC[0] = (r.stdout or "").strip()
    return _ESC[0]


# 生效条件：name 为被测实现里的函数名、arg 为其单个字面量实参源码时，返回该调用结果的 repr（诊断/探针用）。
def _call_probe(name, arg):
    code = ("import sys;sys.path.insert(0, %r);"
            "import review_build as rb;"
            "sys.stdout.write(str(getattr(rb, %r)(%s)))" % (GEN_DIR, name, arg))
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONUTF8="1",
                                                  PYTHONDONTWRITEBYTECODE="1"),
                       timeout=120)
    return (r.stdout or "").strip() or (r.stderr or "").strip()[-160:]


# 生效条件：name 为模块级常量名、root 为占位（保留签名兼容）时，从 GEN_PATH 读出该常量的当前值（串）。
def _const_probe(root, name):
    code = ("import sys;sys.path.insert(0, %r);"
            "import review_build as rb;"
            "sys.stdout.write(str(getattr(rb, %r)))" % (GEN_DIR, name))
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONUTF8="1",
                                                  PYTHONDONTWRITEBYTECODE="1"),
                       timeout=120)
    return (r.stdout or "").strip()


# ---------------------------------------------------------------- 拒绝面探针（A10–A13）

#: 拒绝面探针的缓存：{场景名: (是否被拒, 错误文本)}——每个沙箱只跑一次子进程。
_REJ = {}
#: 断言总数不手写常数——由 `--list` 侧的 `_ASSERT_GROUPS` 在运行期求出，
#: 免得将来加减断言时那个常数静默错掉（手写常数一旦漂移，末行读数就骗人）。
_ASSERT_GROUPS = (("A", 16), ("B", 16), ("C", 8), ("Q", 8))
ASSERT_TOTAL = sum(n for _, n in _ASSERT_GROUPS)
#: `--quiet` 下 **B15 刻意跳过**（它读仓内 CI 定义；在变异沙箱里会被自己拖红），
#: 故静默模式的**期望实跑数**比全量少 1。父进程据此校验子进程真的跑满了判据——
#: 「吐完期望的 RED 后崩掉」不许再被误判 PASS。
ASSERT_TOTAL_QUIET = ASSERT_TOTAL - 1


# 生效条件：scenario 为拒绝面场景名、obj 为真源对象时，子进程跑**被测实现**的 review_build.validate 并把 (是否被拒, 错误文本) 记进 _REJ。
def _validate_probe(scenario, obj):
    code = (
        "import sys, json\n"
        "sys.path.insert(0, %r)\n"
        "import review_build as rb\n"
        "doc = json.loads(sys.stdin.buffer.read().decode('utf-8'))\n"
        "errs = rb.validate(doc)\n"
        "sys.stdout.buffer.write(json.dumps("
        "{'rej': bool(errs), 'err': ' | '.join(errs)}).encode('utf-8'))\n"
        % GEN_DIR)
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                       input=json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, env=dict(os.environ, PYTHONUTF8="1",
                                                     PYTHONDONTWRITEBYTECODE="1"),
                       timeout=120)
    try:
        got = json.loads((r.stdout or b"{}").decode("utf-8"))
    except ValueError:
        got = {}
    _REJ[scenario] = (bool(got.get("rej")), str(got.get("err") or ""))


# 生效条件：scenario 为拒绝面场景名、mutate 为「把一条合法记录改坏一处」的函数、drop_to 非空时改用前 N 条记录，返回该场景是否被校验件拒收。
def _rejects(scenario, mutate, drop_to=None):
    if scenario not in _REJ:
        doc = fixture_doc()
        if drop_to is not None:
            doc["records"] = doc["records"][:drop_to]
        else:
            mutate(doc["records"][0])
        _validate_probe(scenario, doc)
    rej, err = _REJ[scenario]
    REJ_ERR[0] = "[%s] %s" % (scenario, err)
    return rej


def judge(doc, root):
    del _red[:]
    # 探针缓存每次判读都清空：变异自证要在**每个变异体自己的仓根**下重跑本函数，
    # 若沿用上一轮的缓存，Q1/A10–A13 就会读到未变异的实现——判据变空转。
    _ESC[0] = ""
    _REJ.clear()
    group_source(doc)
    group_site(doc, root)
    group_quality(root)
    group_delivery(root)
    return list(_red)


# ================================================================ [C] 交付面
# 为什么要这一组：A/B/Q 三组跑的是**夹具**——它们证明「生成器对夹具的行为」，
# 但**证明不了交付出去的那份真源与那 6 页产物**。若只看 A/B/Q，把 review/data/plugins.json
# 删到只剩 1 条记录、或把 review/site 的页删掉，守卫照样全绿（判据空转）。
# 故本组直接读**仓内真源**并核对**已提交的产物**。

# 生效条件：root 为被测仓根时，对**仓内真源与已提交产物**跑同一批判据，返回红项已并入 _red。
def group_delivery(root):
    print("[C] 交付面（真源 review/data/plugins.json ＋ 已提交产物 review/site 真的被judged）")
    # 用**专用沙箱**：真源与产物都从 ROOT 原样复制，不经夹具生成——
    # 否则夹具生成时会把真实产物当「旧页」清掉（B13 的清理逻辑），[C] 就再也读不到它们。
    droot = make_delivery_sandbox()
    try:
        _judge_delivery(droot)
    finally:
        shutil.rmtree(droot, ignore_errors=True)


# 生效条件：droot 为交付面专用沙箱时，对**已提交面**（DATA_SRC 真源 ＋ SITE_SRC 产物）逐条判读。
def _judge_delivery(droot):
    try:
        real = _json_at_path(DATA_SRC)
    except (OSError, ValueError) as exc:
        ok("C1 real 能读到仓内真源 review/data/plugins.json", False, str(exc))
        return
    recs = real.get("records") or []
    ok("C1 real 仓内真源含 ≥%d 条插件记录" % MIN_PLUGINS, len(recs) >= MIN_PLUGINS,
       "实得 %d" % len(recs))
    ok("C2 real 仓内真源每条 name／version／source_url 非空且为 str",
       all(isinstance(d.get(k), str) and d[k].strip()
           for d in recs for k in ("name", "version", "source_url")))
    ok("C3 real 仓内真源每条五维齐备且 1–5 整数",
       all(set(d.get("dimensions") or {}) == set(DIMENSIONS)
           and all(isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5
                   for v in d["dimensions"].values()) for d in recs))
    ok("C4 real 仓内真源每条 ≥1 条证据且 cmd／output／source／doc／quotes 齐备",
       all(d.get("evidence") and all(
           isinstance(e.get(k), str) and e[k].strip()
           for e in d["evidence"] for k in ("cmd", "output", "source", "doc"))
           and all(e.get("quotes") for e in d["evidence"]) for d in recs))
    ok("C5 real 仓内真源「无读数维度必须记 1」这条硬约束成立",
       all(all(d["dimensions"].get(x) == 1 for x in (d.get("unmeasured_dims") or []))
           for d in recs))
    ok("C6 real 自评条目都带 disclosure",
       all(str(d.get("disclosure") or "").strip()
           for d in recs if d.get("self_review")))
    # C7/C8：判**已提交的产物**（SITE_SRC 那份）与**已提交的真源**（DATA_SRC 那份）对不对得上。
    pages = sorted(n for n in os.listdir(SITE_SRC) if n.endswith(".html")) \
        if os.path.isdir(SITE_SRC) else []
    want = sorted(set(BASE_PAGES) | {"detail_%s.html" % d["slug"] for d in recs})
    if os.environ.get("REVIEW_GUARD_DEBUG"):
        sys.stderr.write("[dbg-C] REAL_ROOT=%r SITE_SRC=%r exists=%s\n"
                         % (REAL_ROOT, SITE_SRC, os.path.isdir(SITE_SRC)))
        sys.stderr.write("[dbg-C] pages=%s\nwant =%s\n" % (pages, want))
    ok("C7 site 已提交产物页集 == 首页/榜单/方法/每插件一页", pages == want,
       "实得 %s" % pages)
    # C8：**每条记录都要有自己的详情页、且页里有它的未测项正文**。
    # 只判「正文在不在」会漏掉「整页缺失」——那时读回空串，而空串恒在页面里（实测踩过）。
    miss = [d["slug"] for d in recs
            if not os.path.isfile(os.path.join(SITE_SRC, "detail_%s.html" % d["slug"]))
            or _md(d["unmeasured"]) not in _read_path(
                SITE_SRC, "detail_%s.html" % d["slug"])]
    ok("C8 site 每条记录都有自己的详情页且页内未测项正文与真源一致", not miss, str(miss))


# 生效条件：root 为沙箱仓根、rel 为相对路径时返回该 JSON 的内容（读不到则抛 OSError/ValueError）。
def _json_at(root, rel):
    with io.open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
        return json.load(fh)


# 生效条件：path 为 JSON 文件绝对路径时返回其内容（读不到则抛 OSError/ValueError）。
def _json_at_path(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


# 生效条件：site_dir 为产物目录、name 为页文件名时返回该页文本（不存在则返回空串）。
def _read_path(site_dir, name):
    p = os.path.join(site_dir, name)
    return io.open(p, encoding="utf-8").read() if os.path.isfile(p) else ""


# 生效条件：无必需形参时判「仓内自带可挂 CI 的检查」——**刻意不放进 judge()**：
# 它读的是仓内的 CI 定义（不是仓外交付说明），且在 `--quiet`/变异面里会被跳过（见 main）。
def check_delivery_doc():
    wf = os.path.join(ROOT, ".github", "workflows", "review-check.yml")
    text = ""
    if os.path.isfile(wf):
        with io.open(wf, encoding="utf-8") as fh:
            text = fh.read()
    ok("B15 ci 仓内自带 CI 定义（--check 漂移闸 ＋ 两个守卫 ＋ 变异自证 ＋ 证据链）",
       bool(text)
       and "scripts/review_build.py --check" in text
       and "tests/test_review_build.py" in text
       and "tests/test_review_build.py --mutate" in text
       and "scripts/evidence_check.py" in text
       and "tests/test_evidence_check.py" in text,
       "路径=%s 存在=%s" % (wf, bool(text)))


# ================================================================ 定点变异（注入映射失效 ⇒ 必红）
# 每条变异 = 把**一条映射**短路（源码级、逐条写进沙箱副本再重跑本守卫），
# 期望转红的断言项**恰好**等于声明集合。
#
# ★ 判据解耦说明（本表为什么长这样）：
#   「榜面总分」这一条链上，**排序**与**求和**都源于同一个 `total_score`——若把 `total_score`
#   短路，榜面次序与榜面分值会**同时**改变，两条判据必然一起红（多红＝语义纠缠）。
#   故本表**不**用「短路 total_score」证明 B5，改用 `format_total`（榜面分值的唯一出口）：
#   只改显示、不动排序，B5 单独红而 B4 不受影响。B4 则由 `_rank_key` 单独证明。
#   这样每条判据各自可红，符合「多红少红都算错」的口径。
#
# ★ 一处**结构性耦合**（如实声明，不假装独立）：
#   slug 收口只有 `slug_ok` 一道闸（白名单本身即排除 `/`、`\\`、`:`、`.`，故路径穿越拼不出来）。
#   A14（路径类输入）与 A15（怪名）测的是**同一道闸的两个侧面**，所以 S6 短路 slug_ok 时
#   两条断言必然一起红——这不是语义纠缠，而是「同一条判据的两个用例集」。
#   早期版本曾另立一道 `slug_path_safe` 作纵深防御，实测被白名单**完全遮蔽**（白名单先拒收，
#   那道闸的行为无从观测、也无法用变异证明），故已删除，只留这一条可被证伪的收口。
MUTATIONS = (
    ("S1", "_rank_key",
     '    return (-row["total"], row["name"])',
     '    return (0, row["name"])', {"B4"}),
    ("S2", "format_total",
     '    return "<b>%d</b>" % int(n)',
     '    return "<b>0</b>"', {"B5"}),
    ("S3", "esc",
     '    return html.escape(str(text), quote=True)',
     '    return str(text)', {"Q1", "Q2", "Q7"}),
    ("S4", "render_detail",
     '        ev_blocks.append("<p><b>① 复跑命令</b></p>")',
     '        ev_blocks.append("")', {"B6"}),
    ("S5", "render_method",
     '        "<h2>%s</h2>" % esc(UNMEASURED_HEAD),',
     '        "<h2>%s</h2>" % esc("略"),', {"B8"}),
    ("S6", "slug_ok",
     '    return bool(SLUG_RE.fullmatch(str(slug)))',
     '    return True', {"A14", "A15"}),
    ("S7", "stale_pages",
     '    for name in sorted(os.listdir(out_dir)):\n        if not name.startswith("detail_") or not name.endswith(".html") or name in keep:\n            continue',
     '    for name in []:\n        if not name.startswith("detail_") or not name.endswith(".html") or name in keep:\n            continue',
     {"B13"}),
    ("S8", "extra_pages",
     '    return sorted(n for n in os.listdir(out_dir)\n                  if n not in names and os.path.isfile(os.path.join(out_dir, n)))',
     '    return []', {"B14"}),
    # S9：**破坏性清理**这条安全面的定点变异。`--out` 是用户给的参数，同仓
    # `scripts/build_site.py` 的默认输出目录恰好也叫 `site`（且两站固定页名重叠）。
    # 去掉 `detail_` 收口后，`stale_pages` 会无差别删掉目录里所有不在本次集合内的 `.html`——
    # 也就是把**别人的产物**删了。故 S9 必须让 B16 恰好转红。
    ("S9", "stale_pages",
     '        if not name.startswith("detail_") or not name.endswith(".html") or name in keep:',
     '        if not name.endswith(".html") or name in keep:',
     {"B16"}),
    ("S10", "validate_record",
     '            qs = e.get("quotes")',
     '            qs = ["mutation-disables-quotes-check"]  # MUT', {"A16"}),
    ("S11", "inline_md",
     '    out = esc(text)',
     '    out = str(text)  # MUT', {"Q7"}),
    ("S12", "page",
     '        "<!DOCTYPE html>",',
     '        "<!DOCTYPE html><!--MUT 00:00-->"',
     {"Q8"}),
    # S13/S14 是**数据面**变异（把仓内真源改坏一处），不是代码面——
    # 因为 C7/C8 要证的正是「守卫真的读了交付的真源与产物」，
    # 只有改真源才能做到「只红 C 组、不牵连任何代码面判据」。
    # 元组形状与代码面一致（old/new 位留空），由 old 以 "data:" 开头区分。
    ("S13", DATA_REL, "data:unmeasured", "", {"C8"}),
    # 真源多一条记录：页集对不上（C7）**且**该记录没有自己的详情页（C8）——
    # 两条判据都在判同一件事实的不同侧面，故如实标成两条都红，不假装独立。
    ("S14", DATA_REL, "data:extrarecord", "", {"C7", "C8"}),
)


def _anchor_preflight():
    """锚点自检：任一**代码面**锚点在当前实现里命中次数 ≠1 → ANCHOR-MISS（退出码 2）。

    数据面变异（锚点以 `data:` 开头）不走这一步——它们改的是真源，不是实现源码。
    """
    src = io.open(os.path.join(ROOT, *GEN_REL.split("/")), encoding="utf-8").read()
    bad = [(mid, src.count(old)) for mid, _rel, old, _new, _exp in MUTATIONS
           if not str(old).startswith("data:") and src.count(old) != 1]
    if not bad:
        return 0
    for mid, n in bad:
        print("  ANCHOR-MISS %s：锚点命中 %d 次（期望 1）" % (mid, n))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


# 生效条件：kind 为数据面变异名、target 为要改写的真源路径时，把 target 改坏一处（不返回复原函数——
# 因为 target 现在是**临时副本**，不需要复原；改完随沙箱一起删掉）。
def _apply_data_mutation(kind, target):
    """数据面变异：改 `target`（调用方传的是**临时副本**，不是已提交真源）。

    为什么必须有这条路径：[C] 组判的就是「真源 ↔ 产物」对不对得上。
    若只改沙箱里那份、而 C 组读已提交那份，这条映射就永远不可能被证伪（判据空转）。
    故让 C 组读 `DATA_SRC`，而 `DATA_SRC` 在变异模式下被 `REVIEW_DATA_SRC` 指向临时副本——
    两边都读同一份被改过的真源，且**已提交真源一个字节都不动**。
    """
    original = io.open(target, encoding="utf-8").read()
    doc = json.loads(original)
    if kind == "data:unmeasured":
        # 改掉第一条记录的未测项正文 ⇒ 与已提交详情页里那段正文对不上（C8 必须发现）。
        # 用「追加」而不是「清空」：清空后 `_md("")` 是空串，而空串恒在页面里，
        # 反而会让 C8 误判为通过（实测踩过）。
        doc["records"][0]["unmeasured"] = doc["records"][0]["unmeasured"] + "（变异注入）"
    elif kind == "data:extrarecord":
        # 真源多一条记录、产物却没有它的页 ⇒ 页集与真源对不上（C7 必须发现）。
        # 这条记录的其它字段与首条相同，故 C8 不会连带变红。
        extra = json.loads(json.dumps(doc["records"][0]))
        extra.update({"slug": "ghost", "name": "Ghost",
                      "source_url": "https://example.invalid/ghost",
                      "version_source": "https://example.invalid/ghost/package.json"})
        doc["records"] = doc["records"] + [extra]
    else:
        raise ValueError("未知的数据面变异：%s" % kind)
    #: 原子替换：万一在写的中途被打断，临时副本也不会变成半截 JSON。
    _write_text_atomic(target, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


# 生效条件：path 为文件路径、text 为完整内容时，先写同目录临时文件再 os.replace 原子替换（避免半截文件）。
def _write_text_atomic(path, text):
    tmp = path + ".tmp-mutation"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _mutate_mode():
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：逐条短路一条映射，对应断言必须**恰好**转红\n")
    #: 数据面变异用的**临时真源**：内容取自已提交真源，但写的是这份副本。
    #: 已提交真源在整轮自证里**只读**——这是硬要求（见 DATA_SRC 的注记）。
    data_tmp_dir = make_scratch_dir()
    data_tmp = os.path.join(data_tmp_dir, "plugins.json")
    shutil.copy(DATA_SRC, data_tmp)

    base_red, base_ran = _run_quiet(ROOT, data_tmp)
    print("  未变异基线：红项 %s（实跑断言 %d）"
          % (sorted(base_red) or "无（应为无）", base_ran))
    bad = []
    if base_red:
        bad.append("基线即转红：%s" % sorted(base_red))
    if base_ran != ASSERT_TOTAL_QUIET:
        bad.append("基线实跑断言数 %d ≠ 期望 %d——判据没跑全，变异自证不可信"
                   % (base_ran, ASSERT_TOTAL_QUIET))
    try:
        for mid, rel, old, new, expect in MUTATIONS:
            d = make_sandbox()
            try:
                #: CI 定义也要随变异体复制——B15 读它；缺了会把 B15 拖红、污染红项集合。
                ci = os.path.join(ROOT, *CI_REL.split("/"))
                if os.path.isfile(ci):
                    cdst = os.path.join(d, *CI_REL.split("/"))
                    os.makedirs(os.path.dirname(cdst), exist_ok=True)
                    shutil.copy(ci, cdst)
                if str(old).startswith("data:"):
                    #: 每个数据面变异都从**已提交真源**重新拷一份副本：否则多个数据面变异会
                    #: 累积在同一个副本上，表的先后顺序变成隐含依赖（早先版本如此）。
                    shutil.copy(DATA_SRC, data_tmp)
                    _apply_data_mutation(old, data_tmp)
                else:
                    # 代码面变异一律打在**生成器**上（rel 位是「目标函数名」，仅作文档/可读性）。
                    p = os.path.join(d, *GEN_REL.split("/"))
                    t = io.open(p, encoding="utf-8").read()
                    io.open(p, "w", encoding="utf-8", newline="\n").write(
                        t.replace(old, new, 1))
                red, ran = _run_quiet(d, data_tmp)
                #: 两个条件都要满足：红项集合**恰好相等**，且子进程**跑满了判据**。
                hit = (red == set(expect)) and (ran == ASSERT_TOTAL_QUIET)
                if not hit:
                    bad.append("%s：红项 %s ≠ 期望 %s，或实跑断言数 %d ≠ %d"
                               % (mid, sorted(red), sorted(expect), ran, ASSERT_TOTAL_QUIET))
                print("  [%s] %s：红项 %d（期望 %d）实跑 %d%s"
                      % ("PASS" if hit else "FAIL", mid, len(red), len(expect), ran,
                         "" if hit else " 实=%s 期=%s" % (sorted(red), sorted(expect))))
            finally:
                shutil.rmtree(d, ignore_errors=True)
    finally:
        shutil.rmtree(data_tmp_dir, ignore_errors=True)
    print("\n定点变异：%s" % ("PASS（逐条恰好命中期望红项）" if not bad
                              else "FAIL —— " + "；".join(bad)))
    print("通过 %d / 失败 %d（变异 %d 组）"
          % (len(MUTATIONS) - len(bad), len(bad), len(MUTATIONS)))
    return 0 if not bad else 1


def _run_quiet(root, data_src=None):
    """在 root 下以 `--quiet` 重跑本守卫，返回 (红项集合, 实跑断言数)。

    显式传两个环境变量给子进程：
      · `REVIEW_COMMITTED_ROOT` —— 子进程的 `ROOT` 是变异沙箱，靠它自己往上找会停在临时目录上；
      · `REVIEW_DATA_SRC` —— 让子进程的 [C] 组去读**临时真源副本**（数据面变异改的就是它），
        已提交真源全程只读。

    **为什么要读回实跑断言数**：早先版本只看 `RED <id>` 行。若某个变异让守卫吐完
    「恰好期望的那些红项」之后**崩在中途**，红项集合仍然相等，变异被误判 PASS——
    判据空转。故子进程必须回报 `RAN <实跑数>`，父进程同时校验它。
    """
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1")
    env["REVIEW_COMMITTED_ROOT"] = REAL_ROOT
    #: 把**本进程的**临时根交给子进程：整轮自证共用一个根，且子进程不清理它
    #: （清理权在 `_SCRATCH_OWNER`，父进程持有）。
    env["REVIEW_SCRATCH_ROOT"] = SCRATCH_ROOT
    if data_src:
        env["REVIEW_DATA_SRC"] = data_src
    r = subprocess.run(
        [sys.executable, "-X", "utf8", os.path.join(root, *GUARD_REL.split("/")), "--quiet"],
        cwd=root, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=600)
    red = set(re.findall(r"^RED (\S+)", r.stdout or "", re.M))
    m = re.search(r"^RAN (\d+)$", r.stdout or "", re.M)
    return red, (int(m.group(1)) if m else -1)


# ================================================================ 主流程

def measure():
    """一次性探针：跑生成器 / --check / --print / fail-closed 四路，留待断言判读。"""
    root = make_sandbox(fixture_doc())
    r = run_gen(root, "--out", OUT_REL)
    LAST_RC[0], LAST_ERR[0] = r.returncode, r.stderr or ""

    # --check 的漂移面**另起一个沙箱**：否则一旦夹具被判非法，主沙箱没有产物，
    # 后续写盘会 FileNotFoundError 把整轮跑挂掉——判据失败应当只红对应断言，不该让守卫崩。
    drift_root = make_sandbox(fixture_doc())
    run_gen(drift_root, "--out", OUT_REL)              # 先真落一次盘，--check 才有产物可比
    rc_c = run_gen(drift_root, "--check", "--out", OUT_REL)
    board = os.path.join(drift_root, *OUT_REL.split("/"), "board.html")
    if os.path.isfile(board):
        with io.open(board, "a", encoding="utf-8") as fh:
            fh.write("漂移注入\n")
    rc_d = run_gen(drift_root, "--check", "--out", OUT_REL)
    CHECK_OK[0] = (rc_c.returncode == 0 and rc_d.returncode == 1
                   and "board.html" in (rc_d.stderr or ""))
    CHECK_ERR[0] = "rc=%s/%s err=%s" % (rc_c.returncode, rc_d.returncode,
                                        (rc_d.stderr or "")[-120:])

    # --print 要指到一个**本来不存在**的输出目录才判得动「不落盘」：
    # 沙箱现在自带已提交产物（review/site），拿它当基准会让这条恒假。
    fresh = make_sandbox(fixture_doc())
    print_out = "review/print_only_probe"
    rc_p = run_gen(fresh, "--out", print_out, "--print")
    PRINT_OK[0] = (rc_p.returncode == 0
                   and "===== board.html =====" in (rc_p.stdout or "")
                   and not os.path.isdir(os.path.join(fresh, *print_out.split("/"))))
    PRINT_ERR[0] = "rc=%s" % rc_p.returncode

    bad_root = make_sandbox({"records": fixture_doc()["records"][:1]})
    bad_out = "review/failclosed_probe"
    rc_b = run_gen(bad_root, "--out", bad_out)
    FC_OK[0] = (rc_b.returncode == 2 and "fail-closed" in (rc_b.stderr or "")
                and "插件数" in (rc_b.stderr or "")
                and not os.path.isdir(os.path.join(bad_root, *bad_out.split("/"))))
    FC_ERR[0] = "rc=%s err=%s" % (rc_b.returncode, (rc_b.stderr or "")[-140:])

    # ---- 旧页清理（B13）：先落 4 条（脚本下限是 3，故 4→3 才不触发 fail-closed），再删 1 条重生成 ----
    four = fixture_doc()
    extra_rec = dict(four["records"][0])
    extra_rec.update({"slug": "delta", "name": "Delta", "version": "9.9.9",
                      "source_url": "https://example.invalid/delta"})
    four["records"] = four["records"] + [extra_rec]
    st_root = make_sandbox(four)
    run_gen(st_root)
    before = "detail_delta.html" in _pages(st_root)
    three = fixture_doc()
    write_data(st_root, three)
    r2 = run_gen(st_root)
    after_gone = "detail_delta.html" not in _pages(st_root)
    STALE_OK[0] = before and after_gone and r2.returncode == 0
    STALE_DETAIL[0] = "落过=%s 重生成后仍在=%s rc=%s" % (before, not after_gone,
                                                         r2.returncode)

    # ---- --check 能否发现「多出来的页」（B14）----
    ex_root = make_sandbox(fixture_doc())
    ex_rc = run_gen(ex_root)
    if not os.path.isdir(os.path.join(ex_root, *OUT_REL.split("/"))):
        raise RuntimeError("B14 前置失败：生成器未产出 review/site（rc=%s）%s"
                           % (ex_rc.returncode, (ex_rc.stderr or "")[-300:]))
    ghost = os.path.join(ex_root, *OUT_REL.split("/"), "detail_ghost.html")
    with io.open(ghost, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("<!DOCTYPE html>\n")
    rc_e = run_gen(ex_root, "--check")
    EXTRA_OK[0] = rc_e.returncode == 1 and "detail_ghost.html" in (rc_e.stderr or "")
    EXTRA_ERR[0] = "rc=%s err=%s" % (rc_e.returncode, (rc_e.stderr or "")[-140:])

    # ---- 外来页必须**不被删**（B16）----
    # 先落一次盘，再往产物目录里放一个「别的生成器的页面」，然后重新生成：
    # 那个文件必须**还在**（只报不删）。这条判的是「不许毁别人的产物」，不是「清理要生效」。
    fr_root = make_sandbox(fixture_doc())
    run_gen(fr_root)
    fr_out = os.path.join(fr_root, *OUT_REL.split("/"))
    foreign = os.path.join(fr_out, "honor.html")
    with io.open(foreign, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("<!DOCTYPE html>\n<!-- 别的生成器的页面 -->\n")
    rc_f = run_gen(fr_root)
    FOREIGN_OK[0] = (rc_f.returncode == 0 and os.path.isfile(foreign))
    FOREIGN_ERR[0] = "rc=%s 外来页仍在=%s" % (rc_f.returncode, os.path.isfile(foreign))
    return root


def main():
    global DIM_MIN, DIM_MAX, MIN_PLUGINS
    if "--list" in sys.argv:
        for mid, fn, _old, _new, exp in MUTATIONS:
            print("  %s  target=%-16s expect_red=%s" % (mid, fn, sorted(exp)))
        return 0
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode()
        root = measure()
        #: 值域是与实现共同钉死的协议常量（真源只有真/假而无绝对值可核），
        #: 故从实现读出后由本件假定为真——单列出来，免得后面读的人以为是循环论证。
        DIM_MIN = int(_const_probe(root, "DIM_MIN"))
        DIM_MAX = int(_const_probe(root, "DIM_MAX"))
        doc = fixture_doc()
        red = judge(doc, root)
        if QUIET:
            # --quiet 只服务定点变异自证：那时 ROOT 是**沙箱**，仓外交付说明取不到，
            # 跑 B15 会把它自己拖红并污染每个变异体的红项集合。故静默模式不跑它。
            for r in sorted(set(red)):
                print("RED %s" % r)
            #: 回报**实跑断言数**：父进程据此判定「判据是跑完了，还是崩在中途」。
            print("RAN %d" % _RUN[0])
            return 1 if red else 0
        # B15 单独判（依赖仓内 CI 定义，不进变异面，见 check_delivery_doc 的注记）。
        check_delivery_doc()
        red = list(_red)
        actual = _RUN[0]
        total = ASSERT_TOTAL
        print()
        if actual != total:
            #: 「少跑」不许伪装成「通过」：某组判据提前 `return` 时那几条根本没执行，
            #: 早先版本照手写常数把它们算成通过。实跑数与期望数不等**本身即红项**。
            print("!! 实跑断言数 %d ≠ 期望 %d —— 有判据没跑到（少跑不等于通过）"
                  % (actual, total))
            red.append("ASSERT-COUNT")
        print("通过 %d / 失败 %d（实跑断言 %d）"
              % (total - len(set(red)), len(set(red)), actual))
        if red:
            print("红项：%s" % sorted(set(red)))
        return 1 if red else 0
    finally:
        if _SCRATCH_OWNER:
            shutil.rmtree(SCRATCH_ROOT, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
