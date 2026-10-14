# -*- coding: utf-8 -*-
"""畸形**输入面**（语法面 ＋ 两个元素面）⇒ fail-closed 点名，不再裸栈／不静默跳过

家族第三批补面。前两批：
  · `test_malformed_root_reports.py`            ＝ **根**形状
  · `test_*_element_shape.py`（build_site / bounty_list / evidence_check）＝ **元素**形状
三处都问同一个问题「**该形状的兄弟面**是否已守」——答案都守了，漏的是这三面：

  ① `bounty_list.load`：真源**不是合法 JSON**（`{"`）⇒ 裸 `json.JSONDecodeError` ＋ rc=1（与漂移撞码）
  ② `evidence_check.audit`：`records` **元素非对象** ⇒ 裸 `AttributeError`（根面 L195、evidence 元素面都已有守卫）
  ③ `build_site`：账本 `events` **元素非对象** ⇒ `render_honor` 的 `until` 生成式裸 `AttributeError`

判据：**点名** ＋ rc=2 ＋ 输出里无 `Traceback`；合法输入逐位保持旧行为（零行为变更）。
反证：`--mutate` 逐条短路守卫 ⇒ 对应断言必须转红（锚点不唯一 ⇒ `[ANCHOR-MISS]` ＋ rc=2）。

用法：python -X utf8 tests/test_malformed_input_reports.py [--mutate]
零第三方依赖、不触网、**不写仓**（全部沙箱在 tempfile 里）。
"""
import sys, os, io, json, tempfile, subprocess
sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ("OK " if ok else "NG ", name, (" — " + detail) if detail else ""))


def _src(rel):
    return io.open(os.path.join(_REPO, *rel.split("/")), encoding="utf-8").read()


def _sandbox(files):
    """把 {相对路径: 文本} 落成临时目录；**绝不写进仓**。"""
    d = tempfile.mkdtemp(prefix="malformed_input_")
    for rel, text in files.items():
        p = os.path.join(d, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        io.open(p, "w", encoding="utf-8", newline="\n").write(text)
    return d


def _run(args, cwd):
    p = subprocess.run([sys.executable, "-X", "utf8"] + args, cwd=cwd,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def _tail(out, n=80):
    lines = [l for l in out.strip().splitlines() if l.strip()]
    return (lines[-1][:n] if lines else "")


# ---------- 三个探针：返回「守卫是否成立」（同一探针供正常态与变异态共用） ----------
def probe_syntax(src_bl):
    """① 真源语法错 ⇒ 无 Traceback ＋ rc=2 ＋ 点名「不是合法 JSON」＋ 点名**实读路径**。"""
    d = _sandbox({"scripts/bounty_list.py": src_bl,
                  "docs/bounty/悬赏.json": '{"items": [\n'})
    rc, out = _run([os.path.join(d, "scripts", "bounty_list.py"), "--check"], d)
    named = os.path.join(d, "docs").replace("\\", "/") in out.replace("\\", "/")
    return (("Traceback" not in out) and rc == 2 and ("不是合法 JSON" in out) and named), \
           "rc=%s tail=%s" % (rc, _tail(out))


_MANIFEST_OK = {"documents": [{"file": "x.txt", "kind": "README", "source_url": "u",
                               "sha256": "0" * 64, "bytes": 0, "fetched_at": "2026-01-01"}]}


def _ev_sandbox(records_val, src_ev=None):
    """测评数据沙箱。清单**必须非空**：`audit` 的清单结构闸排在 records 元素面**之前**，
    空 `documents` 会先在 L18x 被拦下 —— 那样 ② 的「转红」就不是守卫转红，而是**本来就没走到**
    （假反证：变异前后都红，断言空转）。"""
    return _sandbox({"scripts/evidence_check.py": src_ev or SRC_EV,
                     "review/data/plugins.json": json.dumps({"records": records_val},
                                                            ensure_ascii=False),
                     "review/evidence/manifest.json": json.dumps(_MANIFEST_OK,
                                                                 ensure_ascii=False)})


def probe_records_element(src_ev):
    """② records 元素非对象 ⇒ 不裸栈 ＋ rc=2 ＋ 点名 records[0]（CLI 面，供变异复用）。"""
    d = _ev_sandbox([1], src_ev)
    rc, out = _run([os.path.join(d, "scripts", "evidence_check.py"),
                    "--root", d, "--quiet", "--no-repro"], d)
    return (("Traceback" not in out) and rc == 2 and ("records[0]" in out)), \
           "rc=%s tail=%s" % (rc, _tail(out))


def probe_records_element_inproc(ec):
    """② 精确面：直接调 `audit()` —— 必须是点名 `records[0]` 的 `ValueError`。
    为什么还要这一条：CLI 面的 rc=2 只说明「有 ValueError 出去」，精确面才排除了
    「抛的是别的 ValueError／或 AttributeError 被上游吞掉」这两类假阳性。"""
    d = _ev_sandbox([1])
    try:
        ec.audit(root=d, want_repro=False)
    except ValueError as exc:
        return ("records[0]" in str(exc)), "ValueError: %s" % str(exc)[:110]
    except AttributeError as exc:
        return False, "AttributeError（守卫失位）：%s" % str(exc)[:110]
    return False, "未抛（静默通过＝判据失明）"


def probe_records_no_overreject(ec):
    """② 反向面：元素**是**对象时不得被形状判据拦下（防「守卫写得过严，合法输入也被拒」）。"""
    d = _ev_sandbox([{}])
    try:
        rows, bad = ec.audit(root=d, want_repro=False)
    except ValueError as exc:
        return False, "被形状判据误拦：%s" % str(exc)[:110]
    return (isinstance(rows, list) and isinstance(bad, list)), \
           "rows=%d bad=%d" % (len(rows), len(bad))


def probe_ledger_event_element(src_bs):
    """③ 账本 events 元素非对象 ⇒ 无 Traceback ＋ rc=2 ＋ 点名 events[0]。"""
    d = _sandbox({"scripts/build_site.py": src_bs,
                  "scripts/bounty_board.py": _src("scripts/bounty_board.py"),
                  "docs/bounty/ledger.json": json.dumps({"events": [1]})})
    rc, out = _run([os.path.join(d, "scripts", "build_site.py"), "--check",
                    "--ledger", os.path.join(d, "docs", "bounty", "ledger.json"),
                    "--out", os.path.join(d, "site")], d)
    return (("Traceback" not in out) and rc == 2 and ("账本事件不是对象" in out)
            and ("events[0]" in out)), "rc=%s tail=%s" % (rc, _tail(out))


SRC_BL = _src("scripts/bounty_list.py")
SRC_EV = _src("scripts/evidence_check.py")
SRC_BS = _src("scripts/build_site.py")
_ANCHOR_BL = 'raise ValueError("真源不是合法 JSON：%s（%s）" % (path, exc))'
_ANCHOR_EV = 'if not isinstance(_rec, dict):'
_ANCHOR_BS = 'if not isinstance(e, dict):'
# ① 的第二半：`main` 的 try/except —— 它与 `load` 的点名合起来才是「点名 + rc=2」。
# 两条都变异，才证明「无 Traceback ＋ rc=2」这两个子句也**吃重**（只变异一条的话，
# 另一条仍会兜住错误，反证就只覆盖了「点名」而非整条判据）。
_ANCHOR_BL_MAIN = ('    try:\n        doc = load(SRC)\n'
                   '    except (OSError, ValueError) as exc:\n'
                   '        sys.stderr.write("真源读取失败（fail-closed，未写任何产物）：%s\\n" % exc)\n'
                   '        return 2\n')

print('— ① bounty_list：真源不是合法 JSON —')
_ok, _d = probe_syntax(SRC_BL)
check('① 语法错 ⇒ 不裸栈 ＋ rc=2 ＋ 点名「不是合法 JSON」＋ 点名实读路径', _ok, _d)
_d = _sandbox({"scripts/bounty_list.py": SRC_BL,
               "docs/bounty/悬赏.json": _src("docs/bounty/悬赏.json")})
_rc, _out = _run([os.path.join(_d, "scripts", "bounty_list.py"), "--stdout"], _d)
check('① 零行为变更：合法真源仍 rc=0（--stdout）', _rc == 0, 'rc=%s %s' % (_rc, _tail(_out, 60)))

print('— ② evidence_check：records 元素非对象 —')
_ok, _d = probe_records_element(SRC_EV)
check('② records=[1] ⇒ CLI 不裸栈 ＋ rc=2 ＋ 点名 records[0]', _ok, _d)
sys.path.insert(0, os.path.join(_REPO, "scripts"))
import evidence_check as ec

_ok, _detail = probe_records_element_inproc(ec)
check('② 精确面：audit() 抛 ValueError 点名 records[0]（**不是** AttributeError）', _ok, _detail)
_ok, _detail = probe_records_no_overreject(ec)
check('② 反向面：records=[{}]（元素是对象）不被形状判据误拦，仍走正常对账', _ok, _detail)
# 「零行为变更」不由本件承担：全量合法数据的逐位行为由既有 `tests/test_evidence_check.py`
# （600+ 行）钉住，本件只补**畸形面**；两份一起跑才是完整的回归证据。

print('— ③ build_site：账本 events 元素非对象 —')
_ok, _d = probe_ledger_event_element(SRC_BS)
check('③ events=[1] ⇒ 不裸栈 ＋ rc=2 ＋ 点名 events[0]', _ok, _d)
_rc, _out = _run([os.path.join(_REPO, "scripts", "build_site.py"), "--print",
                  "--ledger", os.path.join(_REPO, "docs", "bounty", "ledger.json"),
                  "--out", os.path.join(tempfile.mkdtemp(prefix="malformed_input_out_"), "site")], _REPO)
check('③ 零行为变更：真账本能全量出页（--print ⇒ rc=0）',
      _rc == 0 and "board.html" in _out and "honor.html" in _out,
      'rc=%s %s' % (_rc, _tail(_out, 60)))

print('— D 反向证明（源码锚点）—')
check('D0 ① 语法面守卫锚点命中（恰 1 处）', SRC_BL.count(_ANCHOR_BL) == 1,
      'n=%d' % SRC_BL.count(_ANCHOR_BL))
check('D0 ② records 元素面守卫锚点命中（恰 1 处）', SRC_EV.count(_ANCHOR_EV) == 1,
      'n=%d' % SRC_EV.count(_ANCHOR_EV))
check('D0 ③ 账本事件元素面守卫锚点命中（恰 1 处）＋ 账本入口收敛为单一函数',
      SRC_BS.count(_ANCHOR_BS) == 1 and SRC_BS.count('bb.load_ledger(') == 1,
      'e=%d bb.load_ledger=%d' % (SRC_BS.count(_ANCHOR_BS), SRC_BS.count('bb.load_ledger(')))
def _idx(s, sub):
    return s.find(sub)


def _seg(s, a, b):
    """取 a→b 之间的源码段；任一端缺席即返回空串 ⇒ 断言自然失败（不让判据自己崩）。"""
    i, j = s.find(a), s.find(b)
    return s[i:j] if (i >= 0 and j > i) else ''


# 原先这里断言「旧写法字面量已消失」，**不合格**：它把「实现选择」当成了「缺陷消失」。
# `for rec in recs:` 的正文在 `audit` 里仍逐字存在，只是**之前**加了 validate-then-use 的
# 元素守卫（L203）；字面量缺席既不必要也不充分（改个变量名就能骗过它）。
# ⇒ 改为**性质断言**：守卫必须落在正确函数体内，且必须**排在首个使用点之前**。
_seg_bl = _seg(SRC_BL, 'def load(path):', 'def anchor_html(')
_seg_bs = _seg(SRC_BS, 'def load_events(', 'def main(')
check('D ① 点名守卫落在 `load()` 段内（`def load`→`def anchor_html` 间恰 1 处；`json.load(f)` 恰 1 处）',
      _seg_bl.count(_ANCHOR_BL) == 1 and _seg_bl.count('json.load(f)') == 1,
      'anchor=%d json.load(f)=%d' % (_seg_bl.count(_ANCHOR_BL), _seg_bl.count('json.load(f)')))
check('D ② records 元素守卫**排在首个使用点之前**（validate-then-use；正文允许逐字保留）',
      0 <= _idx(SRC_EV, _ANCHOR_EV) < _idx(SRC_EV, 'for rec in recs:'),
      'guard@%d 首用@%d' % (_idx(SRC_EV, _ANCHOR_EV), _idx(SRC_EV, 'for rec in recs:')))
check('D ③ 账本入口收敛：`def load_events(` 恰 1 处 ＋ 调用点 `= load_events(` 恰 3 处；唯一 `bb.load_ledger(` 在该段内',
      SRC_BS.count('def load_events(') == 1 and SRC_BS.count('= load_events(') == 3
      and SRC_BS.count('bb.load_ledger(') == 1 and _seg_bs.count('bb.load_ledger(') == 1,
      'def=%d 调用=%d bb=%d seg_bb=%d' % (SRC_BS.count('def load_events('),
                                         SRC_BS.count('= load_events('),
                                         SRC_BS.count('bb.load_ledger('),
                                         _seg_bs.count('bb.load_ledger(')))
# 本条是**给后来者**的护栏：既有元素面锚点被污染（多出一处同形字面量）会让兄弟测试静默失绿。
check('D 既有元素面锚点未被污染（build_site `ev` 恰 1 ／ evidence_check 20 空格 `e` 恰 1）',
      SRC_BS.count('if not isinstance(ev, dict):') == 1
      and SRC_EV.count('                    if not isinstance(e, dict):') == 1,
      'ev=%d e20=%d' % (SRC_BS.count('if not isinstance(ev, dict):'),
                        SRC_EV.count('                    if not isinstance(e, dict):')))

print(f'\n通过 {pass_n} / 失败 {fail_n}')

mut_rc = 0
if "--mutate" in sys.argv:
    MUTATIONS = [
        # 注意：`old`／`new` **都不含行首缩进**——`str.replace` 原样替换子串，
        # 若 new 带缩进会叠成 16 空格 ⇒ IndentationError ⇒ 「变红」但红在语法错上（假反证）。
        ("①a 语法面点名（不是合法 JSON）", "scripts/bounty_list.py", _ANCHOR_BL,
         'raise', probe_syntax),
        ("①b main 的 rc=2 兜底（无 Traceback）", "scripts/bounty_list.py", _ANCHOR_BL_MAIN,
         '    doc = load(SRC)\n', probe_syntax),
        ("② records 元素面守卫", "scripts/evidence_check.py", _ANCHOR_EV,
         'if False:', probe_records_element),
        ("③ 账本事件元素面守卫", "scripts/build_site.py", _ANCHOR_BS,
         'if False:', probe_ledger_event_element),
    ]
    print('\n— 反证：逐条短路守卫 ⇒ 对应断言必须转红（否则判据空转）—')
    red = 0
    for label, rel, old, new, probe in MUTATIONS:
        src = _src(rel)
        n = src.count(old)
        if n != 1:
            print('[ANCHOR-MISS] %s：%s 里锚点命中 %d 次（期望 1）⇒ 无法变异，判据失效'
                  % (label, rel, n))
            sys.exit(2)
        ok, detail = probe(src.replace(old, new))
        if ok:
            print('[MUTATE-FAIL] %s：短路后断言仍绿（判据空转）— %s' % (label, detail))
            red += 1
        else:
            print('[MUTATE-OK]   %s：短路后转红 — %s' % (label, detail))
    print('反证结果：%d 条变异，%s' % (len(MUTATIONS), '全部转红' if red == 0 else '%d 条未转红' % red))
    mut_rc = 1 if red else 0

sys.exit(0 if (fail_n == 0 and mut_rc == 0) else 1)
