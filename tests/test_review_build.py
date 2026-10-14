# -*- coding: utf-8 -*-
"""守卫：`scripts/review_build.py`（插件测评子站生成器）——断言 ＋ 定点变异自证。

对象：`scripts/review_build.py`（真源 → 静态子站的**纯函数 + 写盘**，零网络、纯 stdlib）。
真源：`review/data/plugins.json`（读数）＋ `review/data/rubric.json`（判据）；
体例取自同仓 `tests/test_build_site.py`／`tests/test_bounty_list.py`。

为什么另立本件：本子站的成立前提是「**页面上的每个数字都能在真源里找到对应读数**」，
且「**没有读数的项被显式标注为未测、而不是被静默算成好成绩**」——这是**映射规则**，
不是渲染细节。故本件 = ①逐条正反断言（真源 → 榜单／详情／方法页的每条映射）
＋ ②每条映射一个**定点变异**（把该映射短路 ⇒ 对应断言**必然转红**且**恰好**转红；
多红＝断言语义纠缠，少红＝判据空转）。

断言组（共 68 条；`--quiet` 下 B15 刻意跳过，故静默实跑 67）：
  [A] 真源面：条数下限 / 五维齐备 / 值域 / 证据三项齐 / 必填非空 / 版本可锚 / slug 唯一
      ＋ A17–A26：判据表（`rubric.json`）形状与内容 / 两轴一致（null ⇔ basis 空 ⇔ unmeasured_dims）
      / 下标可解析 / rationale 指回证据并写明「为什么不是下一级」/ 5 分确有本机复跑 / 判据版本对齐
      / 真源不许手写总分。A1–A16 判**夹具**，A17–A26 判**真源与判据表本身**。
  [B] 站点面：文件集 / 页数 / 榜单次序 / 已测均值 / 详情证据块 / 边界 / 未测条款 / 口径标注
      ＋ B17–B21：档位推导与独立实现逐维一致 / 三段划分 / 段内次序 / 榜面 = 算得 / 榜面标题。
      B1–B16 判**夹具产物**，B17–B21 判**已提交产物 ↔ 已提交真源**（数据漂移与手改产物的绊线）。
  [C] 交付面：仓内真源 ＋ 已提交产物真的被判（页集 / 详情页 / 未测正文）；
      ＋ C9–C11：自评分列与不降权理由 / 判据表逐维渲染 / 每维档位串。
  [Q] 安全与确定性：HTML 转义 / 注入被转义 / 逐字节一致 / 零第三方 import（Q9：`scripts/` 全量）
      / fail-closed 不落盘 / Q10 不触网（纯文本 ＋ import ＋ 可执行位置三路判）。

用法：
  python -X utf8 tests/test_review_build.py            # 正向：全部断言，末行「通过 N / 失败 M」
  python -X utf8 tests/test_review_build.py --quiet    # 只输出 `RED <id>`（供变异自证解析）
  python -X utf8 tests/test_review_build.py --mutate   # 定点变异自证（逐条须恰好命中期望红项）
  python -X utf8 tests/test_review_build.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中；1 = 有断言失败 / 变异未按预期转红；
        2 = ANCHOR-MISS（锚点在实现里命中次数 ≠1——实现漂移即硬失败）。

★ 沙箱根怎么选（**唯一名 ＋ 真写真删探针 ＋ 回退**）：候选顺序 = 系统临时目录 → 仓根**父目录**
  （即仓根之外）。每个候选都**用 `os.makedirs()`（不带 mode）建一个唯一名目录**，再「真写 ＋ 真删」
  探一次；探不过就换下一个候选，全不过时给出**点名错误**而不是栈回溯。
  两处如实声明：①沙箱根落在**仓根之外**（父目录只读的环境下它会失败——那时给点名错误）；
  ②`REVIEW_SCRATCH_ROOT` 可由外部指定，此时清理权不归本进程。
  为什么**不用 `tempfile.mkdtemp()`**：本机 DSH 文件沙箱下它用 `os.mkdir(d, 0o700)`
  （带 mode 实参）建目录，建出来的目录**子目录建不进、连自己都删不掉**（WinError 5），
  `rmtree(..., ignore_errors=True)` 于是静默失败——实测系统临时目录里累积了一堆
  `review_guard_*` 空壳。同进程对照实验：`os.mkdir/os.makedirs` 不带 mode ⇒ 建／写／整树删全正常。
  为什么沙箱根要**唯一名**、且**不建固定名的壳目录**（如 `.review_guard_tmp`）：① 并发跑两份守卫时
  若共用一个固定根，先结束的那份 `rmtree` 会把另一份正在用的沙箱一起删掉（实测：产物面断言整片
  假红 ＋ 数据副本 FileNotFoundError）；② Windows 把删除失败留下的安全描述符挂在**父目录**上，
  同名目录重建会把旧的拒绝项一并继承（实测：固定名壳里的子目录删不掉）。唯一名把两个坑一起绕开，
  跑完也不留任何空壳。收尾 `_drop_scratch_root()` 用 `os.lstat` **复核**删净没有
  （`os.path.isdir` 会吞掉 OSError），删不净就往 stderr 打一行警告；并注册到 `atexit`，异常退出也收尾。
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
import time
import uuid

#: 本件会在仓内 `sys.path.insert(0, scripts/)` 后 import 生成器——不许因此落下 `__pycache__`
#: （那会让 `git status` 变脏，也让「补丁全为新增」这条边界声明不成立）。
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))          # <仓根>/tests
ROOT = os.path.dirname(HERE)                               # <仓根>
GEN_REL = "scripts/review_build.py"
DATA_REL = "review/data/plugins.json"
#: **真源目录**（整目录复制用）。v2 起 `review/data/` 下不止一份真源（`plugins.json` 读数 ＋
#: `rubric.json` 判据），沙箱必须**整目录**带走——早先逐个文件名列举，漏掉 `rubric.json`，
#: 于是生成器 `load_rubric` fail-closed 成 rc=2、整个守卫崩在 B14 前置（实测踩过）。
DATA_DIR_REL = "review/data"
#: **判据真源**相对路径（A 组判据表读它；同样允许被 `REVIEW_RUBRIC_SRC` 覆盖）。
RUBRIC_REL = "review/data/rubric.json"
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
#: 产物面：同样允许被 `REVIEW_SITE_SRC` 覆盖——产物面变异（Mn9「手改榜面一个均值数字」）
#: 改的是**临时副本**，已提交产物全程只读（与真源同一条纪律）。
SITE_SRC = os.environ.get("REVIEW_SITE_SRC") or os.path.join(
    REAL_ROOT, *OUT_REL.split("/"))
#: 判据真源：允许被 `REVIEW_RUBRIC_SRC` 覆盖——判据面变异（Mn6／Mn7）改的是临时副本。
#: **为什么不把判据变异写进沙箱那份**：生成器 `load_rubric()` 对判据 fail-closed，
#: 判据一坏它就以 rc=2 收场、整站产物不落盘，于是 B/C 组全线假红（多红＝语义纠缠）。
#: 故判据变异只对**守卫的判据表**（A17–A19／A25）可见，生成器读的始终是沙箱里那份好的。
RUBRIC_SRC = os.environ.get("REVIEW_RUBRIC_SRC") or os.path.join(
    REAL_ROOT, *RUBRIC_REL.split("/"))

#: **已提交面（全程只读）**：B17–B21 ／ C5 ／ C9–C11 判的是「**已提交的**真源／判据 ↔
#: **已提交的**产物」，故读这三个常量而不是上列可被环境变量覆盖的别名。
#: 为什么必须分开：数据面／判据面变异改的是别名指向的临时副本，若这些判据跟着别名走，
#: 一个数据变异会同时拖红多条判据（实测的语义纠缠）；分开之后每条变异只红它该红的那条。
COMMITTED_DATA = os.path.join(REAL_ROOT, *DATA_REL.split("/"))
COMMITTED_RUBRIC = os.path.join(REAL_ROOT, *RUBRIC_REL.split("/"))
COMMITTED_SITE = os.path.join(REAL_ROOT, *OUT_REL.split("/"))

QUIET = "--quiet" in sys.argv
_red = []
#: 实跑断言计数（末行 N 的来源；`--quiet` 也会回报给父进程）。
_RUN = [0]

#: 守卫侧**独立声明**（不 import 被守卫对象——否则同错同绿，判据一起空转）。
DIMENSIONS = ("检索质量", "记忆持久", "注入预算", "隐私与本地性", "可验证性")
DIM_MIN, DIM_MAX = 1, 5
MIN_PLUGINS = 3
MIN_PAGES = 4
#: **他评榜门槛**（守卫侧独立声明）：已测维度 ≥ 3/5 才排名。
#: 写成守卫自己的常数（而不是从实现读回）——B18 判的就是「实现的三段划分 == 这个规则」，
#: 从实现读常数会让这条判据变成同义反复。实例漂移（例如实现偷偷把门槛改成 2）时 B18 必红。
MIN_RANKED_COVERAGE = 3
BASE_PAGES = ("index.html", "board.html", "method.html")
#: 标准库 import 白名单。三条纯 stdlib 件**共用**它（生成器 / 探针 / 证据链校验件）——
#: 早先版本只扫生成器，探针与校验件的 import 面零覆盖。
#: `__import__(` / `importlib` 另由 Q4 的文本判据禁掉：`__import__("requests")` 能绕过
#: 「`^\s*(?:import|from)`」这种行首正则（早先版本的变异自己就用过 `__import__("datetime")`，
#: 等于自证了这个绕过面）。
ALLOWED_IMPORTS = {"__future__", "argparse", "datetime", "hashlib", "html",
                   "importlib", "io", "json", "os", "re", "sys"}

#: **网络面禁用名单**（Q10）：站点生成与证据链复算**只许读本地文件**。
#: 名单比 Q4 的 import 白名单更宽——白名单只挡 import 名字，挡不住 `socket.socket(...)`、
#: `urllib.request.urlopen(...)` 这类**用法**，故另起一条判据逐件扫。
#: 判据分两路，因为「名字出现」不等于「网络面」：
#:   ① 纯文本（`urlopen`／`urlretrieve`／`asyncio.open_connection`）——纯 stdlib 件里没有任何
#:      正当用途，连注释里出现都算说不清；
#:   ② 结构化（模块名出现在 import 里，或出现在 `名字.` ／ `名字(` 这种**可执行**位置）。
#: 为什么不能一律按子串判：本仓 `review_build.py` 的注释里就有一处 `httpx`（在讲
#: 「只查 startswith("http") 会放行 http／httpx／httpjunk」），纯子串判据会把注释误判成网络面。
NETWORK_PLAIN = ("urlopen", "urlretrieve", "asyncio.open_connection")
NETWORK_MODULES = ("requests", "httpx", "aiohttp", "socket", "urllib", "ftplib",
                   "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "webbrowser")
#: `http` 单独判：只认 `import http`／`from http…` 与 `http.client` 这种**模块面**，
#: 不把 `http(s)://`、`startswith("http")` 这类**正文里的 URL 讨论**当成网络调用
#: （实测：一律按 `http[.(]` 判会把注释里的 `http(s)://` 误判成调用）。
NETWORK_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(?:%s|http)\b" % "|".join(map(re.escape, NETWORK_MODULES)), re.M)
NETWORK_CALL_RE = re.compile(
    r"\b(?:%s|http\.client)\s*[.(]" % "|".join(map(re.escape, NETWORK_MODULES)))

#: **不得出现在真源记录里的手写总分字段**（A26）：v2 的均值／覆盖率一律由
#: `measured_mean()`／`coverage()` 算出，真源里手写一个总分就会与页面上的算出值两说。
FORBIDDEN_TOTAL_FIELDS = ("total", "total_score", "mean", "average", "score_total")

#: 守卫侧**独立声明**的「可核数字读数」单位白名单（B17 的自算档位用；与生成器同口径但各自成文）。
#: 顺序即正则交替序（长单位在前），避免 `bytes` 被 `B`、`tokens` 被 `tok` 截断。
READING_UNITS = ("%", "bytes", "B", "KB", "MB", "GB", "ms", "s",
                 "tok", "tokens", "条", "个", "次", "倍", "轮", "分")
READING_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|bytes|B|KB|MB|GB|ms|s|tok|tokens|"
                        r"条|个|次|倍|轮|分)")
HIT_READING_RE = re.compile(r"(?:hit\s*@\s*\d+|@\d+)")

#: 证据档位枚举（守卫侧独立声明；B17／C11 自算档位用）。
TIERS = ("none", "prose", "reading", "repro")

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
#: 沙箱根：**本次运行专用的唯一名目录**（见 `_pick_scratch_root`，落在系统临时目录或仓根父目录下）。
#: **每个沙箱一个全新目录**，目录名带本次进程的随机令牌：Windows 会在删掉目录后把安全描述符
#: 留在父目录里，重建同名目录会把旧的拒绝项一并恢复，于是新目录又不可写／删不掉（本机沙箱实测）。
#: 故一律用「从未出现过」的名字，且**不嵌套**（每个沙箱都是自己的仓根，与上游
#: `tests/test_build_site.py` 的「仓根沙箱」体例一致）。`uuid` 属标准库，不违反零依赖。


# 生效条件：path 为目录时把整棵树删掉，并返回**是否真的删净**（用 `os.lstat` 复核）。
# 为什么不能只看 `rmtree(..., ignore_errors=True)`：本机 DSH 沙箱下它对**带 mode 建出来的**
# 目录会静默失败（`rmdir` 报 WinError 5），于是每轮在工作区／临时目录里留一个空壳，
# 事后完全看不出是哪一步没删掉。故这里**复核**删净没有，并重试几次（Windows 上索引器／
# 杀软短暂占住目录会让第一次 rmtree 失败），把结果交给调用方去点名。
# `os.lstat` 而不是 `os.path.isdir`：后者会吞掉 OSError，把「查不了」当成「不存在」。
def _drop_dir(path, tries=3):
    if not path:
        return True
    for _ in range(tries):
        if not os.path.lexists(path):
            return True
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        else:
            shutil.rmtree(path, ignore_errors=True)
        if not os.path.lexists(path):
            return True
        time.sleep(0.2)
    return not os.path.lexists(path)


# 生效条件：parent 为已存在的目录时，在其中用 `os.makedirs()` ＋ 唯一名建一个**全新**目录并返回路径。
# 为什么不用 `tempfile.mkdtemp()`：本机 DSH 文件沙箱下 mkdtemp 内部用 `os.mkdir(d, 0o700)`
# （**带 mode 实参**）建目录，建出来的目录**子目录建不进、连它自己都删不掉**（WinError 5）——
# `rmtree(..., ignore_errors=True)` 于是静默失败，系统临时目录里会累积一堆 `review_guard_*` 空壳
# （实测：TEMP 下十几个）。同进程对照实验：`os.mkdir/os.makedirs` **不带 mode** ⇒ 建、写、整树删全正常。
def _unique_scratch_dir(parent, tag="review_guard"):
    last = None
    for _ in range(32):
        d = os.path.join(parent, "%s_%s" % (tag, uuid.uuid4().hex[:8]))
        try:
            os.makedirs(d)          # 不带 mode——与 mkdtemp 的差别就在这里
        except OSError as exc:
            last = exc
            continue
        if os.path.isdir(d):
            return d
        last = OSError("建出来的 %s 不可用" % d)
    raise OSError("在 %s 下建不出可用的唯一目录（最后一次：%s）" % (parent, last))


# 生效条件：root 为候选沙箱根时，**真写**一次（建子目录 ＋ 落一个文件）再**真删**，返回该位置是否可用。
# 只判「目录建出来了」不算探到：本机沙箱下 mkdtemp 的目录既建得出、又写不进／删不掉——
# 只看 mkdtemp 是否抛异常会把「不可用的临时目录」当成可用（实测踩过，留了一堆空壳）。
def _scratch_usable(root):
    probe = os.path.join(root, "write_probe")
    try:
        os.makedirs(os.path.join(probe, "x"))
        with io.open(os.path.join(probe, "x", "p.txt"), "w", encoding="utf-8",
                     newline="\n") as fh:
            fh.write("ok")
    except OSError:
        _drop_dir(probe)
        return False
    return _drop_dir(probe)


# 生效条件：无必需形参时返回一个可写的沙箱根——**本次运行专用**（唯一名目录，不与其它运行共享）。
# 候选顺序：① 系统临时目录；② 仓根**父目录**（仓根之外）。每个候选都过「真写 ＋ 真删」探针；
# 全都不过时给出**点名错误**（退出码 2）而不是栈回溯。
# 为什么根要用**唯一名**、而不是固定的 `.review_guard_tmp` 之类：
#   ① 并发跑两份守卫时若共用一个固定根，先结束的那份 `rmtree` 会把另一份正在用的沙箱一起删掉
#      （实测：产物面断言整片假红 ＋ 数据副本 FileNotFoundError）；
#   ② Windows 把删除失败留下的安全描述符挂在**父目录**上，同名目录重建会把旧的拒绝项一并继承
#      （见上），于是固定名会一轮比一轮难删。唯一名把两个坑一起绕开，跑完不留任何固定名空壳。
def _pick_scratch_root():
    env = os.environ.get("REVIEW_SCRATCH_ROOT")
    if env:
        return env
    tried = []
    for parent in (tempfile.gettempdir(), os.path.dirname(ROOT)):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            tried.append("%s：父目录建不出（%s）" % (parent, exc))
            continue
        try:
            d = _unique_scratch_dir(parent)
        except OSError as exc:
            tried.append("%s：建不出唯一子目录（%s）" % (parent, exc))
            continue
        if _scratch_usable(d):
            return d
        tried.append("%s：真写＋真删探针不过（%s）" % (parent, d))
    raise SystemExit(
        "[错误] 守卫找不到可写的沙箱根：%s。可用环境变量 REVIEW_SCRATCH_ROOT 指定一个可写目录。"
        % "；".join(tried))


SCRATCH_ROOT = _pick_scratch_root()
#: 清理权归**创建者**：父进程建根、父进程清；子进程（变异体守卫）只是借住，
#: 绝不 `rmtree` 整根——否则会把父进程放在根下的临时真源一起删掉（实测报 FileNotFoundError）。
_SCRATCH_OWNER = not os.environ.get("REVIEW_SCRATCH_ROOT")
RUN_TOKEN = uuid.uuid4().hex[:12]
_SANDBOX_N = [0]


# 生效条件：无必需形参时删除**本次运行**的沙箱根；删不净就往 stderr 打一行警告（退出码不变）。
# 幂等：根已经不在（正常路径）时静默返回。子进程（非 owner）不碰它。
def _drop_scratch_root():
    if not _SCRATCH_OWNER:
        return
    if not _drop_dir(SCRATCH_ROOT):
        sys.stderr.write("[警告] 沙箱根删除未净（本机沙箱下带 mode 建的目录会这样）：%s\n"
                         % SCRATCH_ROOT)


#: 异常退出（未捕获的异常／`SystemExit`）也要收尾——`finally` 只覆盖 main() 正常走完的情形。
atexit.register(_drop_scratch_root)


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
    #: 真源要带上——[C] 交付面组与 A17–A26 判据表读它。
    #: **整目录复制 `review/data/**`，不是逐个文件名列举**：该目录下现在有 `plugins.json`
    #: （读数）与 `rubric.json`（判据）两份真源，逐个列举漏掉后者会让生成器 `load_rubric`
    #: fail-closed 成 rc=2，整个守卫崩在 B14 前置；将来再加真源文件（例如档位枚举表）也不会漏。
    #: **产物目录（review/site）刻意不预置**：预置旧页会让「旧页清理」（B13）在每个变异体上假红。
    data_src_dir = os.path.join(ROOT, *DATA_DIR_REL.split("/"))
    if os.path.isdir(data_src_dir):
        ddst_dir = os.path.join(root, *DATA_DIR_REL.split("/"))
        os.makedirs(ddst_dir, exist_ok=True)
        for name in sorted(os.listdir(data_src_dir)):
            sp = os.path.join(data_src_dir, name)
            if os.path.isfile(sp):
                shutil.copy(sp, os.path.join(ddst_dir, name))
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


# ---------------------------------------------------------------- 守卫侧独立实现（B17／C11 自算用）
# 为什么另写一份：B17 要证的是「实现算出来的档位 == 按规则读 evidence ＋ basis 手算的档位」。
# 若直接 import 被守卫对象，同错同绿，判据就空转了。

# 生效条件：text 为某条证据的 output 时返回其中是否有可核数字读数（独立实现，与生成器同口径）。
def _reading_ok(text):
    """「可核数字读数」：数字 ＋ 单位白名单，或 `hit@k`／`@k` 形态。"""
    s = str(text or "")
    return bool(READING_RE.search(s) or HIT_READING_RE.search(s))


# 生效条件：v 为真源维度值时返回整数分，`null`／不可转值返回 None（独立实现）。
def _score_of(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# 生效条件：d 为记录、dim 为维度名时返回**守卫侧自算**的档位串（none／prose／reading／repro）。
def _tier_of(d, dim):
    """读 `evidence` ＋ `dim_basis` 自算档位：null/none basis → none；≥1 条本机复跑 → repro；
    否则 ≥1 条 output 有可核数字读数 → reading；否则（有证据但没数字）→ prose。"""
    if _score_of((d.get("dimensions") or {}).get(dim)) is None:
        return "none"
    basis = (d.get("dim_basis") or {}).get(dim)
    ev = d.get("evidence") if isinstance(d.get("evidence"), list) else []
    entries = [ev[i] for i in (basis if isinstance(basis, list) else [])
               if isinstance(i, int) and not isinstance(i, bool)
               and 0 <= i < len(ev) and isinstance(ev[i], dict)]
    if not entries:
        return "none"
    if any(str(e.get("kind") or "") == "本机复跑" for e in entries):
        return "repro"
    if any(_reading_ok(e.get("output")) for e in entries):
        return "reading"
    return "prose"


# 生效条件：d 为记录时返回**守卫侧自算**的已测维度均值（无已测维度给 0.0）。
def _mean_of(d):
    dims = d.get("dimensions") if isinstance(d.get("dimensions"), dict) else {}
    vals = [v for v in (_score_of(dims.get(k)) for k in DIMENSIONS) if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


# 生效条件：d 为记录时返回**守卫侧自算**的已测维度数。
def _cover_of(d):
    dims = d.get("dimensions") if isinstance(d.get("dimensions"), dict) else {}
    return len([k for k in DIMENSIONS if _score_of(dims.get(k)) is not None])


# 生效条件：d 为记录、dim 为维度名时返回该维是否「口径自洽的已测维度」——
# 非 null、basis 非空、且不在 unmeasured_dims 里。
# **为什么 A22／A23／A24 只在这个集合上判**：这三条判的是「已测维度的 rationale 质量」
# 与「5 分维度的 repro 硬条件」，而「非 null ⇔ basis 非空 ⇔ 不在 unmeasured_dims」
# 这条一致性映射由 **A20 单独记账**。若不收口，一处脏数据（例如 Mn2：把 null 维改成 1
# 却仍留在 unmeasured_dims 里）会同时红 A20／A22／A23——那是语义纠缠，不是三条判据都在判。
# 收口不构成漏判：这类维度一定已经让 A20 转红，整体判据仍然拒收。
def _well_measured(d, dim):
    if _score_of((d.get("dimensions") or {}).get(dim)) is None:
        return False
    if dim in {str(x) for x in (d.get("unmeasured_dims") or [])}:
        return False
    b = (d.get("dim_basis") or {}).get(dim)
    return isinstance(b, list) and len(b) >= 1


# 生效条件：d 为记录、dim 为维度名时返回该维的 dim_basis 原值（非数组一律当空数组，读不崩）。
def _basis_list(d, dim):
    b = (d.get("dim_basis") or {}).get(dim)
    return b if isinstance(b, list) else []


# 生效条件：d 为记录、dim 为维度名时返回该维 dim_basis 命中的证据条目（越界／非整数下标跳过）。
def _basis_entries_of(d, dim):
    ev = d.get("evidence") if isinstance(d.get("evidence"), list) else []
    return [ev[i] for i in _basis_list(d, dim)
            if isinstance(i, int) and not isinstance(i, bool)
            and 0 <= i < len(ev) and isinstance(ev[i], dict)]


# 生效条件：d 为记录时返回违反「null ⇔ dim_basis 为空 ⇔ 在 unmeasured_dims 里」双向一致的维度名
# （守卫侧独立实现；A20 用）。
def _basis_both_ways_bad(d):
    bad = []
    dims = d.get("dimensions") if isinstance(d.get("dimensions"), dict) else {}
    basis = d.get("dim_basis") if isinstance(d.get("dim_basis"), dict) else {}
    um = {str(x) for x in (d.get("unmeasured_dims") or [])}
    for k in DIMENSIONS:
        v = _score_of(dims.get(k))
        nonempty = isinstance(basis.get(k), list) and len(basis[k]) >= 1
        if v is None:
            if nonempty or k not in um:
                bad.append(k)
        elif not nonempty or k in um:
            bad.append(k)
    return bad


# 生效条件：v 为分值（int／float）时返回榜面显示形态（与生成器同口径：round 2 位后的最短串）。
def _fmt(v):
    return str(round(float(v), 2))


# 生效条件：无必需形参时返回判据真源顶层 version（夹具的 rubric_version 要等于它）。
def _rubric_version_at(path):
    """判据真源的 version（读不到给空串，交由生成器 fail-closed 点名）。"""
    try:
        with io.open(path, encoding="utf-8") as fh:
            return str((json.load(fh) or {}).get("version") or "")
    except (OSError, ValueError):
        return ""


# 生效条件：score 为某维分值时返回夹具该维的 dim_rationale——必须指回具名证据（「证据 1」）
# 并写明「为什么不是下一级」（≤4 分时含「未给 N+1」），否则生成器 fail-closed、守卫一条断言都跑不到。
def _fixture_rationale(dim, score):
    tail = "" if score >= DIM_MAX else \
        "；未给 %d 因夹具只给到下界侧读数，无更高一级的对照。" % (score + 1)
    return "%s：证据 1 给出该维夹具读数 %d%s" % (dim, score, tail)


# 生效条件：无必需形参时返回一份可覆盖各映射面的真源夹具（三条记录；含一条注入文本，用来证转义是活的）。
def fixture_doc():
    def rec(slug, name, dims, ev, unmeasured="未测 ＋ 夹具：本条用于守卫，非真实测评。",
            version="1.2.3"):
        dim_map = dict(zip(DIMENSIONS, dims))
        return {"name": name, "slug": slug, "version": version,
                # 版本面必须锚在**不可变引用**（tag／commit）：这是生成器的硬判据。
                "version_source": "https://example.invalid/%s/v%s/package.json" % (slug, version),
                "version_checked_at": "2026-10-13",
                "self_review": False,
                "source_url": "https://example.invalid/%s" % slug,
                "reviewed_at": "2026-10-13", "dimensions": dim_map,
                # ★ v2 真源的形状（生成器强制）：每个维度都要 dim_basis（证据下标）与
                #   dim_rationale（指回具名证据 ＋ 为什么不是更高一级）；`null` 维度的
                #   dim_basis 必须为空、并进 unmeasured_dims。
                #   夹具五维**都给读数**（不留 null）：A3「五维 1–5 整数」判的就是夹具，
                #   留一个 null 会让那条既有断言假红；null 面由 [C] 组的真源与 B17 的真实记录覆盖。
                "dim_basis": {k: [0] for k in DIMENSIONS},
                "dim_rationale": {k: _fixture_rationale(k, dim_map[k])
                                  for k in DIMENSIONS},
                "unmeasured_dims": [],
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
    # 三个已测均值互不相同（3.0／3.4／2.2，且五维齐测故与求和序同序）——否则「关掉排序」时
    # `(0, name)` 仍可能与期望同序，判据就空转了。这是夹具的**必要条件**，不是凑数。
    # 顶层 rubric_version 必须等于判据真源的 version（生成器 fail-closed 的硬判据）；
    # 读**本仓根下**那份（= 沙箱随后会复制进自己仓根的那一份），故夹具与生成器读到的必是同一份。
    return {"rubric_version": _rubric_version_at(
                os.path.join(ROOT, *RUBRIC_REL.split("/"))),
            "records": [
                rec("alpha", "Alpha", [5, 4, 3, 2, 1], ev("alpha")),
                rec("beta", "Beta", [4, 4, 4, 3, 2], ev("beta")),
                rec("gamma", "Gamma", [3, 3, 2, 2, 1], ev("gamma"), version="1.2.4"),
            ]}


# ================================================================ [A] 真源面

def group_source(doc):
    print("[A] 真源面（条数下限 / 五维齐备 / 值域 / 证据三项 / 必填非空 / 版本 / slug 唯一 ＋ "
          "判据表形状 / 两轴一致 / 下标 / rationale / 版本对齐 / 禁手写总分）")
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

    # ---------------------------------------------------------------- A17–A26（v2 判据表 ＋ 真源）
    # 与 A1–A16 的分工：A1–A16 判「夹具 → 生成器的行为」；这 10 条判**判据真源与真源本身**
    # （读 `RUBRIC_SRC`／`DATA_SRC` 两个可被变异覆盖的别名——判据面／数据面定点变异改的就是它们）。
    # 每条只判一件事实：档位表形状（A17）、判据表内容（A18）、5 分硬条件被声明（A19）、
    # 三处一致（A20）、下标可解析（A21）、rationale 指回证据（A22）、rationale 写明为何不更高（A23）、
    # 5 分确有本机复跑（A24）、判据版本对齐（A25）、真源不许手写总分（A26）。
    try:
        real = _json_at_path(DATA_SRC)
    except (OSError, ValueError) as exc:
        real = {}
        print("  [注] 真源读不到（A17–A26 将逐条点名）：%s" % exc)
    try:
        rub = _json_at_path(RUBRIC_SRC)
    except (OSError, ValueError) as exc:
        rub = {}
        print("  [注] 判据真源读不到（A17–A26 将逐条点名）：%s" % exc)
    if not isinstance(real, dict):
        real = {}
    if not isinstance(rub, dict):
        rub = {}
    rrecs = [d for d in (real.get("records") or []) if isinstance(d, dict)]
    levels = rub.get("levels") if isinstance(rub.get("levels"), dict) else {}
    feats = rub.get("features") if isinstance(rub.get("features"), dict) else {}
    want_levels = {str(n) for n in range(DIM_MIN, DIM_MAX + 1)}

    def _lv(dim, n):
        lv = levels.get(dim)
        return lv.get(str(n)) if isinstance(lv, dict) else None

    ok("A17 rubric-cover 判据真源 levels 键集合 == 五维，且每维恰含 %d–%d 五级"
       % (DIM_MIN, DIM_MAX),
       set(levels) == set(DIMENSIONS)
       and all(isinstance(levels.get(k), dict) and set(levels[k]) == want_levels
               for k in DIMENSIONS),
       "实得 %s" % sorted(levels))
    # A18 只判**在册的**级（缺级由 A17 单独记账）：否则 Mn6「删掉某一级」会同时红两条（多红＝语义纠缠）。
    ok("A18 rubric-must 每级 meaning 非空，且 must 里的特征名都在 features 里",
       bool(levels) and all(
           isinstance(spec, dict) and bool(str(spec.get("meaning") or "").strip())
           and isinstance(spec.get("must"), list)
           and all(str(f) in feats for f in spec["must"])
           for k in DIMENSIONS if isinstance(levels.get(k), dict)
           for spec in levels[k].values()),
       "features=%s" % sorted(feats))
    ok("A19 five-needs-repro 每一维第 5 级的 must 都含 has_repro（5 分硬条件被声明）",
       all(isinstance(_lv(k, DIM_MAX), dict)
           and "has_repro" in (_lv(k, DIM_MAX).get("must") or [])
           for k in DIMENSIONS),
       "实得 %s" % {k: (_lv(k, DIM_MAX) or {}).get("must")
                    for k in DIMENSIONS if isinstance(_lv(k, DIM_MAX), dict)})
    ok("A20 basis-both-ways 非 null 维 ⇒ dim_basis 非空；null 维 ⇒ basis 空**且**在 "
       "unmeasured_dims；非 null 维**不得**在 unmeasured_dims",
       bool(rrecs) and all(not _basis_both_ways_bad(d) for d in rrecs),
       "违规 %s" % [(d.get("slug"), _basis_both_ways_bad(d)) for d in rrecs
                    if _basis_both_ways_bad(d)])
    bad_idx = [(d.get("slug"), k, x) for d in rrecs for k in DIMENSIONS
               for x in _basis_list(d, k)
               if isinstance(x, bool) or not isinstance(x, int)
               or not (0 <= x < len(d.get("evidence") or []))]
    ok("A21 basis-index dim_basis 每个下标都是 int（非 bool）且在 range(len(evidence)) 内",
       bool(rrecs) and not bad_idx, "越界／非整数 %s" % bad_idx[:6])
    bad_ref, bad_why, bad_five = [], [], []
    for d in rrecs:
        n_ev = len(d.get("evidence") or [])
        slug = d.get("slug")
        for k in DIMENSIONS:
            if not _well_measured(d, k):
                continue
            v = _score_of((d.get("dimensions") or {}).get(k))
            r = str((d.get("dim_rationale") or {}).get(k) or "")
            refs = [int(x) for x in re.findall(r"证据\s*(\d+)", r)]
            if not r.strip() or not any(1 <= x <= n_ev for x in refs):
                bad_ref.append("%s/%s" % (slug, k))
            if v < DIM_MAX and not re.search(r"(?:未给|不给|不是)\s*%d" % (v + 1), r):
                bad_why.append("%s/%s=%s" % (slug, k, v))
            if v == DIM_MAX:
                entries = [e for e in _basis_entries_of(d, k) if isinstance(e, dict)]
                if not any(str(e.get("kind") or "") == "本机复跑" for e in entries):
                    bad_five.append("%s/%s" % (slug, k))
    ok("A22 rationale-evidence 非 null 维 dim_rationale 非空，且含「证据 N」且 1 ≤ N ≤ evidence 条数",
       bool(rrecs) and not bad_ref, "违规 %s" % bad_ref[:6])
    ok("A23 rationale-why-not-higher 分数 ≤ %d 的维度，rationale 须含（未给／不给／不是）分数+1"
       % (DIM_MAX - 1),
       bool(rrecs) and not bad_why, "违规 %s" % bad_why[:6])
    # A24 **直接来自数据**（不经 rubric）：这样 A19（判据表声明了 has_repro）与
    # A24（真源里 5 分维确实有本机复跑）可以**分别**被变异触发（Mn7 vs Mn1），互不遮蔽。
    ok("A24 five-has-repro 分数 == %d 的维度，dim_basis 指向的证据里 ≥1 条 kind == 本机复跑"
       % DIM_MAX,
       bool(rrecs) and not bad_five, "违规 %s" % bad_five[:6])
    ok("A25 rubric-version 真源顶层 rubric_version == 判据真源 version",
       bool(str(real.get("rubric_version") or "").strip())
       and real.get("rubric_version") == rub.get("version"),
       "真源 %r ≠ 判据 %r" % (real.get("rubric_version"), rub.get("version")))
    hand_total = [(d.get("slug"), k) for d in rrecs for k in FORBIDDEN_TOTAL_FIELDS if k in d]
    ok("A26 no-manual-total 真源记录不得出现手写总分字段（%s）——均值／覆盖率一律算出"
       % "／".join(FORBIDDEN_TOTAL_FIELDS),
       bool(rrecs) and not hand_total, "实得 %s" % hand_total)


# ================================================================ [B] 站点面

def group_site(doc, root):
    print("[B] 站点面（文件集 / 页数 / 榜单次序 / 已测均值 / 证据块 / 边界 / 未测条款 / 口径标注 "
          "＋ 已提交面的档位推导 / 三段划分 / 段内次序 / 榜面=算得 / 榜面标题）")
    recs = doc["records"]
    expect = sorted(set(BASE_PAGES) | {"detail_%s.html" % d["slug"] for d in recs})
    names = _pages(root)
    ok("B1 rc0 生成器退出码 0（真源 → 子站落盘）", LAST_RC[0] == 0,
       "rc=%s err=%s" % (LAST_RC[0], LAST_ERR[0][-160:]))
    ok("B2 files 页面集合 == 首页/榜单/方法/每插件一页（无缺无多）", names == expect,
       "实得 %s" % names)
    ok("B3 pages 页数 ≥ %d（验收标准：≥4 页）" % MIN_PAGES, len(names) >= MIN_PAGES,
       "实得 %d" % len(names))

    # 次序与分值**各自**取期望：
    #   B4 只按规则重排原始五维（不经被守卫对象的排序键），故「关掉分值显示」不会连带红 B4；
    #      而「关掉排序」令榜面退化成字典序 ≠ 已测均值序，故必红 B4（夹具三个均值互不相同）。
    #   B5 只看取值集合、不看顺序，故「关掉排序」不牵连 B5。
    # 两类突变分别推翻**不同**的期望形态，正是让每条判据各自可红的关键。
    # ★ v2 口径（与生成器同步；夹具五维齐测，故均值序与求和序同序）：
    #   榜面报的是**已测维度均值**（不再是五维求和），次序是 `(-均值, -覆盖率, 插件名)`。
    def order_by_rule(items):
        return [d["name"] for d in sorted(
            items, key=lambda d: (-_mean_of(d), -_cover_of(d), d["name"]))]

    want = order_by_rule(recs)
    board = _read(root, "board.html")
    order = re.findall(r'<a href="detail_[^"]+">([^<]+)</a>', board)
    ok("B4 order 榜单次序 == 已测均值降序（同均值按覆盖率降序、再按插件名升序）",
       order == want, "实得 %s 期望 %s" % (order, want))
    # B5 把榜面「已测均值」当取值集合比，不看顺序（榜面分值的唯一出口是 format_total）。
    got_means = sorted(re.findall(r"<td><b>([\d.]+)</b></td>", board))
    ok("B5 mean 榜面已测均值取值集合 == 按真源算出的已测均值集合（不读手写字段）",
       got_means == sorted(_fmt(_mean_of(d)) for d in recs),
       "实得 %s" % got_means)

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

    # ---------------------------------------------------------------- B17–B21（判**已提交**面）
    # ★ 为什么读 `COMMITTED_*` 而不是 `DATA_SRC`／`SITE_SRC` 这些别名：
    #   这几条判的是「**已提交的**真源 ↔ **已提交的**产物」，且要与数据面变异解耦——
    #   若跟着别名走，S13／S14（数据面变异）会把它们一起拖红（多红＝语义纠缠）。
    #   产物面变异（Mn9「手改榜面一个均值数字」）只改临时副本，经 `REVIEW_SITE_SRC` 指进来。
    #   B17–B19 走子进程探针调**被测实现**（`dim_tiers()`／`leaderboard()`）——故代码面变异
    #   （改档位推导、改排序键）能真的把它们证伪；对照物是守卫侧**独立实现**（不是同一份代码）。
    impl = _impl_snapshot(COMMITTED_DATA)
    board_c = _read_path(SITE_SRC, "board.html")
    try:
        cdoc = _json_at_path(COMMITTED_DATA)
    except (OSError, ValueError) as exc:
        cdoc = {}
        print("  [注] 已提交真源读不到：%s" % exc)
    crecs = [d for d in (cdoc.get("records") or []) if isinstance(d, dict)]

    tier_diff = []
    for d in crecs:
        slug = str(d.get("slug"))
        got = (impl.get("tiers") or {}).get(slug) or {}
        for k in DIMENSIONS:
            if got.get(k) != _tier_of(d, k):
                tier_diff.append((slug, k, got.get(k), _tier_of(d, k)))
    ok("B17 tiers-derived 每条每维 dim_tiers() == 守卫侧自算档位（读 evidence ＋ dim_basis）",
       bool(crecs) and not tier_diff,
       "不一致（slug/维/实现/自算）%s" % tier_diff[:4])

    want_self = sorted(str(d.get("slug")) for d in crecs if d.get("self_review"))
    want_ins = sorted(str(d.get("slug")) for d in crecs
                      if not d.get("self_review") and _cover_of(d) < MIN_RANKED_COVERAGE)
    want_rank = sorted(str(d.get("slug")) for d in crecs
                       if not d.get("self_review") and _cover_of(d) >= MIN_RANKED_COVERAGE)
    got_groups = {k: [str(x) for x in (impl.get("groups") or {}).get(k) or []]
                  for k in ("ranked", "insufficient", "self")}
    all_slugs = [str(d.get("slug")) for d in crecs]
    parts = [set(got_groups[k]) for k in ("ranked", "insufficient", "self")]
    disjoint = all(not (parts[i] & parts[j]) for i in range(3) for j in range(i + 1, 3))
    #: 逐段**钉死**现行真源的期望（数据漂移的绊线）：他评榜 dsh-auto-memory→dsh-mnemon、
    #: 证据不足为空、自评仅 dsh-memory。写死这三个名字是有意的——真源一变这里就红。
    pinned = {"ranked": ["dsh-auto-memory", "dsh-mnemon"], "insufficient": [],
              "self": ["dsh-memory"]}
    #: 现行真源的**期望读数**（同样是有意写死的数据漂移绊线）：
    #: 均值／覆盖率／自评。改了分数、改了未测维度、或把自评改成他评，这里当场红。
    pinned_nums = {"dsh-memory": ("4.0", 4, True),
                   "dsh-mnemon": ("3.0", 3, False),
                   "dsh-auto-memory": ("3.8", 5, False)}
    got_nums = {str(d.get("slug")): (_fmt(_mean_of(d)), _cover_of(d),
                                     bool(d.get("self_review"))) for d in crecs}
    ok("B18 leaderboard-split 三段划分 == 自评／他评且覆盖率 < %d／其余，且并集为全集、两两不交"
       % MIN_RANKED_COVERAGE,
       bool(crecs) and sorted(got_groups["self"]) == want_self
       and sorted(got_groups["insufficient"]) == want_ins
       and sorted(got_groups["ranked"]) == want_rank
       and disjoint and sorted(set().union(*parts)) == sorted(all_slugs)
       and got_groups == pinned and got_nums == pinned_nums,
       "实得 %s（期望 %s）／读数 %s（期望 %s）"
       % (got_groups, pinned, got_nums, pinned_nums))

    def _order(seg):
        return [str(d.get("slug")) for d in sorted(seg, key=lambda d: (
            -_mean_of(d), -_cover_of(d), str(d.get("name"))))]

    want_order = {"ranked": _order([d for d in crecs if not d.get("self_review")
                                    and _cover_of(d) >= MIN_RANKED_COVERAGE]),
                  "insufficient": _order([d for d in crecs if not d.get("self_review")
                                          and _cover_of(d) < MIN_RANKED_COVERAGE]),
                  "self": _order([d for d in crecs if d.get("self_review")])}
    ok("B19 rank-order 每段内次序 == 按 (-已测均值, -覆盖率, 插件名) 排序的结果",
       bool(crecs) and all(got_groups[k] == want_order[k]
                           for k in ("ranked", "insufficient", "self")),
       "实得 %s 期望 %s" % (got_groups, want_order))

    # B20：榜面「已测均值／覆盖率」**逐条**与算出值一致——钉住「榜面 = 算得」，不许手写。
    # 读**已提交**真源而不是别名：数据面变异改的是别名那份，若这里跟着走，
    # 一条只该红 A 组的变异会顺手把 B20 也拖红（多红＝语义纠缠）；
    # 反过来，产物被手改（Mn9）而真源没动时，这条**必须**红——它判的就是这一对。
    rows = re.findall(r"<tr>.*?</tr>", board_c, re.S)
    bad_cells = []
    for d in crecs:
        slug = str(d.get("slug"))
        row = next((r for r in rows if ("detail_%s.html" % slug) in r), "")
        want_cells = ("<td><b>%s</b></td>" % _fmt(_mean_of(d)),
                      "<td>%d/%d</td>" % (_cover_of(d), len(DIMENSIONS)))
        if not row or not all(c in row for c in want_cells):
            bad_cells.append((slug, want_cells))
    ok("B20 board-shows-computed 榜面每条记录的「已测均值／覆盖率」== 按真源算出的值（不许手写）",
       bool(crecs) and not bad_cells, "对不上 %s" % bad_cells[:4])

    heads = re.findall(r"<h2>(.*?)</h2>", board_c, re.S)
    ok("B21 board-heading 榜面 <h2> 含「已测维度均值降序」且**不含**「总分降序」",
       bool(heads) and any("已测维度均值降序" in h for h in heads)
       and not any("总分降序" in h for h in heads)
       and "总分降序" not in board_c,
       "实得 h2=%s" % [h for h in heads if "降序" in h])

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

    # Q9：零第三方依赖的**动态覆盖**面——Q4 只扫三个**点名的**件，新加一个脚本就漏了。
    # 这里改成「把 `scripts/` 下所有 .py 都扫一遍」（连新代码一起覆盖），判据与 Q4 同口径。
    dyn, dyn_bad = [], []
    sdir = os.path.join(ROOT, "scripts")
    for name in sorted(os.listdir(sdir)) if os.path.isdir(sdir) else []:
        if not name.endswith(".py"):
            continue
        p = os.path.join(sdir, name)
        src = io.open(p, encoding="utf-8").read()
        dyn.append(name)
        got = {x.split(".")[0] for x in
               re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", src, re.M)}
        if got - ALLOWED_IMPORTS or "__import__(" in src or "import_module(" in src:
            dyn_bad.append((name, sorted(got - ALLOWED_IMPORTS)))
    ok("Q9 stdlib-only `scripts/` 下**每一个** .py 都在标准库白名单内（新脚本自动纳入，无动态 import 绕过）",
       bool(dyn) and not dyn_bad, "扫到 %s；越界 %s" % (dyn, dyn_bad))

    # Q10：**不触网**判据——Q4 的白名单只挡 import 名字，挡不住 `socket.socket(...)`、
    # `urllib.request.urlopen(...)` 这类用法。三条纯 stdlib 件逐件扫（含新增的 rubric 读取代码）。
    net_hits = []
    for rel in ("scripts/review_build.py", "scripts/evidence_probe.py", "scripts/evidence_check.py"):
        p = os.path.join(ROOT, *rel.split("/"))
        if not os.path.isfile(p):
            continue
        src = io.open(p, encoding="utf-8").read()
        net_hits += ["%s：%s" % (rel, face) for face in NETWORK_PLAIN if face in src]
        net_hits += ["%s：import %s" % (rel, m.group(0).strip())
                     for m in NETWORK_IMPORT_RE.finditer(src)]
        net_hits += ["%s：调用 %s" % (rel, m.group(0))
                     for m in NETWORK_CALL_RE.finditer(src)]
    ok("Q10 no-network 三个脚本没有任何网络面（纯文本 ＋ import ＋ 可执行位置三路判）",
       not net_hits, "实得 %s" % net_hits[:6])


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
_IMPL = [None]
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


# 生效条件：data_path 为一份真源 JSON 路径时，子进程载入**被测实现**并回传
# {"tiers": {slug: {维: 档位}}, "groups": {段: [slug…]}}——B17–B19 的对照物是守卫侧独立实现。
def _impl_snapshot(data_path):
    """子进程跑被测实现的 dim_tiers()／leaderboard()（读沙箱里那份实现，故代码面变异可见）。"""
    if _IMPL[0] is not None:
        return _IMPL[0]
    code = (
        "import sys, json\n"
        "sys.path.insert(0, %r)\n"
        "import review_build as rb\n"
        "with open(sys.argv[1], encoding='utf-8') as fh:\n"
        "    doc = json.load(fh)\n"
        "recs = doc.get('records') or []\n"
        "by = {str(d.get('slug')): d for d in recs}\n"
        "out = {'tiers': {s: rb.dim_tiers(d) for s, d in by.items()},\n"
        "       'groups': {k: [str(r.get('slug')) for r in v]\n"
        "                  for k, v in rb.leaderboard(recs).items()},\n"
        "       'mean': {s: rb.measured_mean(d) for s, d in by.items()},\n"
        "       'coverage': {s: rb.coverage(d) for s, d in by.items()}}\n"
        "sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode('utf-8'))\n"
        % GEN_DIR)
    try:
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", code, data_path],
                           capture_output=True, env=dict(os.environ, PYTHONUTF8="1",
                                                         PYTHONDONTWRITEBYTECODE="1"),
                           timeout=120)
        _IMPL[0] = json.loads((r.stdout or b"{}").decode("utf-8"))
    except (OSError, ValueError):
        _IMPL[0] = {}
    return _IMPL[0]


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
_ASSERT_GROUPS = (("A", 26), ("B", 21), ("C", 11), ("Q", 10))
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
    _IMPL[0] = None
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
    print("[C] 交付面（真源 review/data/plugins.json ＋ 已提交产物 review/site 真的被judged）"
          "＋ 口径写明面（分列理由 / 判据表渲染 / 逐维档位）")
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
    # C3：v2 口径——维度值可以是 `null`（该维**无任何证据**），其余必须是 1–5 整数。
    # v1 曾要求「五维全为 1–5 整数」，那与现行真源（未测维度记 `null`）冲突：
    # 未测不是「最低档」，把它写死成整数等于要求真源把「未知」伪装成一个分数。
    ok("C3 real 仓内真源每条五维齐备，且每维是 `null`（无任何证据）或 1–5 整数",
       all(set(d.get("dimensions") or {}) == set(DIMENSIONS)
           and all(v is None or (isinstance(v, int) and not isinstance(v, bool)
                                 and 1 <= v <= 5)
                   for v in d["dimensions"].values()) for d in recs))
    ok("C4 real 仓内真源每条 ≥1 条证据且 cmd／output／source／doc／quotes 齐备",
       all(d.get("evidence") and all(
           isinstance(e.get(k), str) and e[k].strip()
           for e in d["evidence"] for k in ("cmd", "output", "source", "doc"))
           and all(e.get("quotes") for e in d["evidence"]) for d in recs))
    # C5：v2 口径——v1 的「未测维度必须写成 1」已废止，改为
    # 「**记 `null` ⟺ `dim_basis` 为空（无任何证据）⟺ 列在 `unmeasured_dims` 里**」
    # （双向一致：漏报与误列都算不成立）。这是改口径，不是放宽：v1 那条约束本身已被废止。
    # ★ 读的是**已提交真源**（`COMMITTED_DATA`）：与 A20（读可被数据面变异覆盖的 `DATA_SRC`）
    #   分工——否则 Mn2（把 null 维改成 1 却仍留在 unmeasured_dims 里）会同时红 A20 与 C5
    #   （多红＝语义纠缠，一条变异只该红它那一处映射）。
    try:
        committed = _json_at_path(COMMITTED_DATA)
    except (OSError, ValueError):
        committed = {}
    c_recs = [d for d in (committed.get("records") or []) if isinstance(d, dict)]
    ok("C5 real 仓内真源「记 `null` ⟺ 列在 unmeasured_dims 里」双向一致成立",
       bool(c_recs) and all(
           sorted(_basis_both_ways_bad(d)) == []
           for d in c_recs), "违规 %s" % [(d.get("slug"), _basis_both_ways_bad(d))
                                          for d in c_recs if _basis_both_ways_bad(d)])
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

    # ---------------------------------------------------------------- C9–C11（口径被写明的产物面）
    # 这三条判的是「**口径**在已提交产物里真的写出来了」：分列／不降权的理由（C9）、
    # 判据真源的 5 级表逐维渲染（C10）、每一维的档位串（C11）。
    # 报告里说不清的口径 = 没写的口径，故这三条落成可红判据（而不是「我写了注释」）。
    board_p = _read_path(SITE_SRC, "board.html")
    ok("C9 self-split-reason 榜面同时含自评**分列理由**与**不降权理由**两个锚点串",
       "为什么分列" in board_p and "为什么不降权" in board_p,
       "分列=%s 不降权=%s" % ("为什么分列" in board_p, "为什么不降权" in board_p))

    # C10 读**已提交判据**（COMMITTED_RUBRIC）：判据面变异（Mn6 删掉某一级）只对
    # A 组判据表可见，产物仍取自未变异那份实现，若这里跟着变异走会假红（多红＝语义纠缠）。
    try:
        c_rub = _json_at_path(COMMITTED_RUBRIC)
    except (OSError, ValueError) as exc:
        c_rub = {}
        print("  [注] 已提交判据真源读不到：%s" % exc)
    c_levels = c_rub.get("levels") if isinstance(c_rub.get("levels"), dict) else {}
    meth_p = _read_path(SITE_SRC, "method.html")
    miss_lv = []
    for k in DIMENSIONS:
        lv = c_levels.get(k)
        spec = lv.get("3") if isinstance(lv, dict) else None
        head = str((spec or {}).get("meaning") or "")[:12]
        if not head or _md(head) not in meth_p:
            miss_lv.append((k, head))
    ok("C10 rubric-table-rendered 方法页逐维渲染判据真源的 5 级表（各维第 3 级 meaning 前 12 字在场）",
       bool(meth_p) and not miss_lv, "缺 %s" % miss_lv)

    # C11：每个详情页必须逐维给出该维的档位串（none／prose／reading／repro），
    # 档位由守卫侧**独立实现**从 evidence ＋ dim_basis 自算——与页面上印的那一格逐维比对。
    tier_miss = []
    for d in c_recs:
        page = _read_path(SITE_SRC, "detail_%s.html" % d.get("slug"))
        for k in DIMENSIONS:
            m = re.search(r"<tr><td>%s</td>.*?<td><code>(%s)</code></td>"
                          % (re.escape(k), "|".join(TIERS)), page, re.S)
            if not m or m.group(1) != _tier_of(d, k):
                tier_miss.append((d.get("slug"), k, m.group(1) if m else None,
                                  _tier_of(d, k)))
    ok("C11 detail-shows-tier 每个详情页都含该记录每一维的档位串（与自算档位逐维一致）",
       bool(c_recs) and not tier_miss, "对不上 %s" % tier_miss[:4])


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
#   「榜面分值」这一条链上，**次序**与**分值**都源于同一个 `leaderboard()` 行——若把它短路，
#   榜面次序与榜面分值会**同时**改变，两条判据必然一起红（多红＝语义纠缠）。
#   故本表**不**用「短路 leaderboard 行」证明 B5，改用 `format_total`（榜面分值的唯一出口）：
#   只改显示、不动排序，B5 单独红而 B4 不受影响。B4 则由 `_rank_key` 单独证明。
#   这样每条判据各自可红，符合「多红少红都算错」的口径。
#
# ★ 变异载体的三类（由锚点前缀区分）：
#   · 代码面：直接改沙箱里那份**生成器源码**（old 是源码锚点，preflight 会核对命中次数 = 1）；
#   · 数据面（`data:`）：改 `DATA_SRC` 的**临时副本**（读 `REVIEW_DATA_SRC` 的 A17–A26 与
#     [C] 组看得到），已提交真源一个字节不动；
#   · 判据面（`rubric:`）：改**判据临时副本**（只有 A17–A19／A25 看得到）——生成器读的始终是
#     沙箱里那份**未变异**的 rubric，否则一删级就 fail-closed 成 rc=2、整站判据全线假红；
#   · 产物面（`site:`）：改 `SITE_SRC` 的**临时副本**（经 `REVIEW_SITE_SRC` 指进来，B20 看得到）。
#   三份临时副本**每次变异前都从已提交面重拷**，避免多个变异互相污染（表的先后顺序不成为隐含依赖）。
#
# ★ 一处**结构性耦合**（如实声明，不假装独立）：
#   slug 收口只有 `slug_ok` 一道闸（白名单本身即排除 `/`、`\\`、`:`、`.`，故路径穿越拼不出来）。
#   A14（路径类输入）与 A15（怪名）测的是**同一道闸的两个侧面**，所以 S6 短路 slug_ok 时
#   两条断言必然一起红——这不是语义纠缠，而是「同一条判据的两个用例集」。
#   早期版本曾另立一道 `slug_path_safe` 作纵深防御，实测被白名单**完全遮蔽**（白名单先拒收，
#   那道闸的行为无从观测、也无法用变异证明），故已删除，只留这一条可被证伪的收口。
MUTATIONS = (
    ("S1", "_rank_key",
     '    return (-row["mean"], -row["coverage"], row["name"])',
     '    return (0, row["name"])', {"B4"}),
    ("S2", "format_total",
     '    return "<b>%s</b>" % _fmt_num(n)',
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

    # ---- Mn1–Mn11：v2 两轴口径的新判据面（真源／判据表／产物）逐条定点变异 ----
    # Mn1：dsh-mnemon「记忆持久」3 → 5。其 basis=[3] 指向**公开文档转引**，没有本机复跑 ⇒
    #      5 分的硬条件在**数据**里不成立（A24）。判据表那边（A19）不受影响——两条各自可红。
    ("Mn1", DATA_REL, "data:mnemon-persist-5", "", {"A24"}),
    # Mn2：dsh-mnemon「注入预算」null → 1，**不移出** unmeasured_dims（同时 basis 仍为空）。
    #      这正是 v1 的坏法（把「未知」写成一个可求和的分数）⇒ A20 必红。
    #      为什么只红 A20：rationale 质量（A22／A23）与 5 分硬条件（A24）只在**口径自洽的
    #      已测维度**上判（`_well_measured`），而这条维度已被 A20 单独记账——不收口就会一次红三条。
    ("Mn2", DATA_REL, "data:mnemon-budget-1", "", {"A20"}),
    # Mn3：给 null 维挂上 basis=[0]（仍是 null、仍在 unmeasured_dims）⇒ 「null ⇒ basis 空」破 ⇒ A20。
    ("Mn3", DATA_REL, "data:mnemon-budget-basis", "", {"A20"}),
    # Mn4：删掉 dsh-auto-memory「检索质量」rationale 里的「未给 3」⇒ 2 分没写「为什么不是 3」⇒ A23。
    ("Mn4", DATA_REL, "data:automem-retrieval-why", "", {"A23"}),
    # Mn5：把 dsh-memory「检索质量」rationale 里的「证据 1、2」改成「两条证据」⇒ 不再指回具名证据 ⇒ A22。
    ("Mn5", DATA_REL, "data:memory-retrieval-ref", "", {"A22"}),
    # Mn6：删掉判据真源「注入预算」的第 3 级 ⇒ 级数不是 1–5 五级 ⇒ A17（在册级的 meaning／must 仍合法，故 A18 不牵连）。
    ("Mn6", RUBRIC_REL, "rubric:drop-inject-level3", "", {"A17"}),
    # Mn7：把五维第 5 级 must 里的 has_repro 删掉 ⇒ 「5 分必须有本机复跑」这条声明消失 ⇒ A19。
    #      真源侧 5 分维本身仍有本机复跑，故 A24 不牵连（两条各自可红，正是本表要的口径）。
    ("Mn7", RUBRIC_REL, "rubric:drop-has-repro", "", {"A19"}),
    # Mn8：顶层 rubric_version 改成 "1.0" ⇒ 与判据真源 version 不一致 ⇒ A25。
    ("Mn8", DATA_REL, "data:rubric-version-1.0", "", {"A25"}),
    # Mn9：**手改产物**——把榜面上一个「已测均值」数字改掉 1 个字符（真源不动）⇒「榜面 = 算得」破 ⇒ B20。
    ("Mn9", OUT_REL, "site:boardmean", "", {"B20"}),
    # Mn10：把一维的 dim_basis 下标改成 99（越界）⇒ 下标指不到读数 ⇒ A21。
    ("Mn10", DATA_REL, "data:basis-index-99", "", {"A21"}),
    # Mn11：给某条记录加一个手写字段 total ⇒ 真源里出现「手写总分」⇒ A26。
    ("Mn11", DATA_REL, "data:manual-total", "", {"A26"}),
)

#: 非代码面变异的锚点前缀（preflight 不对它们核锚点命中次数——它们改的是数据／判据／产物）。
NONCODE_PREFIXES = ("data:", "rubric:", "site:")


def _anchor_preflight():
    """锚点自检：任一**代码面**锚点在当前实现里命中次数 ≠1 → ANCHOR-MISS（退出码 2）。

    非代码面变异（锚点以 `data:`／`rubric:`／`site:` 开头）不走这一步——
    它们改的是真源／判据／产物，不是实现源码，锚点命中次数对它们没有意义。
    """
    src = io.open(os.path.join(ROOT, *GEN_REL.split("/")), encoding="utf-8").read()
    bad = [(mid, src.count(old)) for mid, _rel, old, _new, _exp in MUTATIONS
           if not str(old).startswith(NONCODE_PREFIXES) and src.count(old) != 1]
    if not bad:
        return 0
    for mid, n in bad:
        print("  ANCHOR-MISS %s：锚点命中 %d 次（期望 1）" % (mid, n))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


# 生效条件：recs 为记录列表、slug 为插件 slug 时返回该记录（找不到抛 ValueError——变异表写错就当场炸）。
def _rec_by_slug(doc, slug):
    for d in doc.get("records") or []:
        if isinstance(d, dict) and str(d.get("slug")) == slug:
            return d
    raise ValueError("变异找不到记录 slug=%s" % slug)


# 生效条件：kind 为数据面变异名、target 为要改写的真源路径时，把 target 改坏一处（不返回复原函数——
# 因为 target 现在是**临时副本**，不需要复原；改完随沙箱一起删掉）。
def _apply_data_mutation(kind, target):
    """数据面变异：改 `target`（调用方传的是**临时副本**，不是已提交真源）。

    为什么必须有这条路径：A17–A26 与 [C] 组判的就是「真源 ↔ 产物」对不对得上。
    若只改沙箱里那份、而判据读已提交那份，这条映射就永远不可能被证伪（判据空转）。
    故让它们读 `DATA_SRC`，而 `DATA_SRC` 在变异模式下被 `REVIEW_DATA_SRC` 指向临时副本——
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
    elif kind == "data:mnemon-persist-5":
        # 把「记忆持久」记成 5，而它的 basis 指向的是**公开文档转引**（无本机复跑）⇒ A24 必红。
        _rec_by_slug(doc, "dsh-mnemon")["dimensions"]["记忆持久"] = 5
    elif kind == "data:mnemon-budget-1":
        # 把 null 维写成一个分数（1）却**不移出** unmeasured_dims，且 basis 仍为空 ⇒ A20 必红。
        _rec_by_slug(doc, "dsh-mnemon")["dimensions"]["注入预算"] = 1
    elif kind == "data:mnemon-budget-basis":
        # 给 null 维挂上 basis ⇒ 「null ⇒ dim_basis 为空」破 ⇒ A20 必红。
        _rec_by_slug(doc, "dsh-mnemon")["dim_basis"]["注入预算"] = [0]
    elif kind == "data:automem-retrieval-why":
        # 删掉「未给 3」⇒ 2 分没写「为什么不是下一级」⇒ A23 必红（其余判据不受影响）。
        rec = _rec_by_slug(doc, "dsh-auto-memory")
        rec["dim_rationale"]["检索质量"] = rec["dim_rationale"]["检索质量"].replace(
            "；未给 3 因", "；因", 1)
    elif kind == "data:memory-retrieval-ref":
        # 把「证据 1、2」换成不提具名证据的说法 ⇒ A22 必红（分与「未给 5」都还在，故只红这一条）。
        rec = _rec_by_slug(doc, "dsh-memory")
        rec["dim_rationale"]["检索质量"] = rec["dim_rationale"]["检索质量"].replace(
            "证据 1、2", "两条证据", 1)
    elif kind == "data:rubric-version-1.0":
        doc["rubric_version"] = "1.0"
    elif kind == "data:basis-index-99":
        # 下标越界 ⇒ 指不到读数 ⇒ A21 必红。挑一个**非 5 分**维（4 分），
        # 免得连带触发「5 分必须有本机复跑」（A24）——定点变异只该红一处映射。
        _rec_by_slug(doc, "dsh-memory")["dim_basis"]["记忆持久"] = [99]
    elif kind == "data:manual-total":
        # 真源里手写一个总分字段 ⇒ A26 必红（v2 的均值一律算出，不许手写）。
        _rec_by_slug(doc, "dsh-memory")["total"] = 19
    else:
        raise ValueError("未知的数据面变异：%s" % kind)
    #: 原子替换：万一在写的中途被打断，临时副本也不会变成半截 JSON。
    _write_text_atomic(target, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


# 生效条件：kind 为判据面变异名、target 为判据临时副本路径时，把该副本改坏一处。
def _apply_rubric_mutation(kind, target):
    """判据面变异：改 `target`（**临时副本**）。

    这份副本只喂给守卫的判据表（经 `REVIEW_RUBRIC_SRC`），**不**喂给生成器——
    生成器对判据 fail-closed，判据一坏它就以 rc=2 收场、整站产物不落盘，
    于是 B/C 组全线假红（多红＝语义纠缠）。定点变异要的是「只红判据表那一条」。
    """
    with io.open(target, encoding="utf-8") as fh:
        doc = json.load(fh)
    if kind == "rubric:drop-inject-level3":
        # 删掉某一维的一级 ⇒ 级数不是 1–5 五级 ⇒ A17 必红（在册级的 meaning／must 仍合法，A18 不牵连）。
        doc["levels"]["注入预算"].pop("3", None)
    elif kind == "rubric:drop-has-repro":
        # 五维第 5 级都不再声明 has_repro ⇒「5 分硬条件被声明」这条消失 ⇒ A19 必红。
        for k in DIMENSIONS:
            spec = (doc.get("levels") or {}).get(k, {}).get("5")
            if isinstance(spec, dict) and isinstance(spec.get("must"), list):
                spec["must"] = [f for f in spec["must"] if f != "has_repro"]
    else:
        raise ValueError("未知的判据面变异：%s" % kind)
    _write_text_atomic(target, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


# 生效条件：src 为产物目录、dst 为要落一份副本的目录时，把 src 下的 .html 逐页复制过去。
def _copy_site(src, dst):
    """把产物目录整份复制到 `dst`（产物面变异用的临时副本；只认本站会生成的 .html）。"""
    os.makedirs(dst, exist_ok=True)
    if os.path.isdir(src):
        for name in sorted(os.listdir(src)):
            p = os.path.join(src, name)
            if os.path.isfile(p) and name.endswith(".html"):
                shutil.copy(p, os.path.join(dst, name))
    return dst


# 生效条件：kind 为产物面变异名、site_dir 为产物**临时副本**目录时，把榜面改坏一处（真源不动）。
def _apply_site_mutation(kind, site_dir):
    """产物面变异：改 `site_dir`（**临时副本**，经 `REVIEW_SITE_SRC` 指给子进程守卫）。

    为什么必须有这条路径：`--check` 与 [C] 组判的是「产物 == 真源」，
    但「榜面数字**确实**是算出来的」这条只能靠「真源没动、产物被手改」来证伪——
    否则 B20 就是拿生成器自己的输出比它自己算的值，判据空转。
    """
    if kind != "site:boardmean":
        raise ValueError("未知的产物面变异：%s" % kind)
    p = os.path.join(site_dir, "board.html")
    src = io.open(p, encoding="utf-8").read()
    #: 只改**一个字符**：把第一个 `<td><b>均值</b></td>` 的小数位 +1（模 10，必与原值不同）。
    m = re.search(r"<td><b>(\d+)\.(\d)</b></td>", src)
    if not m:
        raise ValueError("产物面变异找不到可改的均值数字：%s" % p)
    digit = str((int(m.group(2)) + 1) % 10)
    fixed = src[:m.start()] + "<td><b>%s.%s</b></td>" % (m.group(1), digit) + src[m.end():]
    _write_text_atomic(p, fixed)


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
    #: 各面变异用的**临时副本**：内容取自已提交面，但写的都是副本。
    #: 已提交真源／判据／产物在整轮自证里**只读**——这是硬要求（见 DATA_SRC 的注记）。
    #: 三份副本都住同一个临时目录，每个变异前**重新拷**（表的先后顺序不成为隐含依赖）。
    data_tmp_dir = make_scratch_dir()
    data_tmp = os.path.join(data_tmp_dir, "plugins.json")
    rubric_tmp = os.path.join(data_tmp_dir, "rubric.json")
    site_tmp = os.path.join(data_tmp_dir, "site")
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
            over = {}
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
                    over["data_src"] = data_tmp
                elif str(old).startswith("rubric:"):
                    #: 判据面变异：同样每次重拷一份临时副本（判据只喂守卫的判据表，不喂生成器）。
                    shutil.copy(COMMITTED_RUBRIC, rubric_tmp)
                    _apply_rubric_mutation(old, rubric_tmp)
                    over["rubric_src"] = rubric_tmp
                elif str(old).startswith("site:"):
                    #: 产物面变异：每次重拷一份产物临时副本（已提交产物只读）。
                    _copy_site(COMMITTED_SITE, site_tmp)
                    _apply_site_mutation(old, site_tmp)
                    over["site_src"] = site_tmp
                else:
                    # 代码面变异一律打在**生成器**上（rel 位是「目标函数名」，仅作文档/可读性）。
                    p = os.path.join(d, *GEN_REL.split("/"))
                    t = io.open(p, encoding="utf-8").read()
                    io.open(p, "w", encoding="utf-8", newline="\n").write(
                        t.replace(old, new, 1))
                red, ran = _run_quiet(d, **over)
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


def _run_quiet(root, data_src=None, rubric_src=None, site_src=None):
    """在 root 下以 `--quiet` 重跑本守卫，返回 (红项集合, 实跑断言数)。

    显式传环境变量给子进程：
      · `REVIEW_COMMITTED_ROOT` —— 子进程的 `ROOT` 是变异沙箱，靠它自己往上找会停在临时目录上；
      · `REVIEW_DATA_SRC` —— 数据面变异改的那份**临时真源副本**（A17–A26 与 [C] 组读它）；
      · `REVIEW_RUBRIC_SRC` —— 判据面变异改的那份**临时判据副本**（只有 A17–A19／A25 读它）；
      · `REVIEW_SITE_SRC` —— 产物面变异改的那份**临时产物副本**（B20／C7–C11 读它）。
    四者缺省时一律回落到**已提交面**，故未变异基线跑的仍是「已提交真源 ↔ 已提交产物」。

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
    if rubric_src:
        env["REVIEW_RUBRIC_SRC"] = rubric_src
    if site_src:
        env["REVIEW_SITE_SRC"] = site_src
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
        #: 删不净要**说出来**（一行 stderr 警告，退出码不变）——早先 `rmtree(..., ignore_errors=True)`
        #: 把失败吞得干干净净，本机沙箱下每轮留一个空壳却无从追查。
        _drop_scratch_root()


if __name__ == "__main__":
    sys.exit(main())
