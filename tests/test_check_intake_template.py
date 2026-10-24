# -*- coding: utf-8 -*-
# 守卫：check_intake_template.py 的 --mutate 定点变异自证。
import io, json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, 'scripts', 'check_intake_template.py')
def _run_fixture(rows):
    fd, path = tempfile.mkstemp(suffix='.json'); os.close(fd)
    io.open(path, 'w', encoding='utf-8').write(json.dumps(rows))
    env = dict(os.environ); env['PYTHONUTF8'] = '1'
    r = subprocess.run([sys.executable, '-X', 'utf8', SCRIPT, '--offline-fixture', path],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=60)
    os.unlink(path)
    return r
GOOD = [{'issue': 1, 'body': 'x <!-- intake:v1 {"project":"memory","difficulty":"medium","impact":"B","target":"FuRongJun-1999/dsh-memory"} -->'}]
def test_clean_fixture_passes():
    r = _run_fixture(GOOD)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
def test_repo_drift_warns():
    rows = [{'issue': 2, 'body': 'x <!-- intake:v1 {"repo":"FuRongJun-1999/lingshu","severity":"P1"} -->'}]
    r = _run_fixture(rows)
    assert 'field drift' in r.stdout
def test_project_mismatch_fails():
    rows = [{'issue': 3, 'body': 'x <!-- intake:v1 {"project":"memory","target":"FuRongJun-1999/lingshu"} -->'}]
    r = _run_fixture(rows)
    assert r.returncode == 1 and 'project=memory' in r.stdout
def test_bad_difficulty_fails():
    rows = [{'issue': 4, 'body': 'x <!-- intake:v1 {"project":"memory","difficulty":"small","target":"FuRongJun-1999/dsh-memory"} -->'}]
    r = _run_fixture(rows)
    assert r.returncode == 1 and 'difficulty' in r.stdout
def test_p_severity_maps():
    rows = [{'issue': 5, 'body': 'x <!-- intake:v1 {"target":"FuRongJun-1999/lingshu","severity_hint":"P1"} -->'}]
    r = _run_fixture(rows)
    assert 'impact' not in [l.split(':')[0] for l in r.stdout.split(chr(10)) if 'not in vocab' in l]
def test_no_marker_reports():
    rows = [{'issue': 6, 'body': 'no marker here'}]
    r = _run_fixture(rows)
    assert 'no intake:v1 marker' in r.stdout


# —— 畸形 fixture 必须**点名 + 退 2**，不得裸栈（本笔新增）——
# 为什么需要：旧实现对五类坏输入全部裸栈（FileNotFoundError / JSONDecodeError /
# TypeError / KeyError），调用者只看到 traceback，分不清「fixture 坏了」还是
# 「自审器自己坏了」。口径：**输入坏 = 2**（判据不可用），**有违例 = 1**（判据结论）。
def _run_raw(text):
    fd, path = tempfile.mkstemp(suffix='.json'); os.close(fd)
    io.open(path, 'w', encoding='utf-8').write(text)
    env = dict(os.environ); env['PYTHONUTF8'] = '1'
    r = subprocess.run([sys.executable, '-X', 'utf8', SCRIPT, '--offline-fixture', path],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=60)
    os.unlink(path)
    return r


def test_bad_fixture_fails_closed():
    cases = (
        ('{"issue":1}', '顶层不是数组'),
        ('["x"]', '元素不是对象'),
        ('[{"body":"x"}]', '缺 issue 键'),
        ('[', '不是合法 JSON'),
    )
    for raw, want in cases:
        r = _run_raw(raw)
        both = (r.stdout or '') + (r.stderr or '')
        assert r.returncode == 2, (raw, r.returncode, both[:200])
        assert want in both, (raw, want, both[:200])
        assert 'Traceback' not in both, (raw, both[:200])


def test_missing_fixture_fails_closed():
    env = dict(os.environ); env['PYTHONUTF8'] = '1'
    r = subprocess.run([sys.executable, '-X', 'utf8', SCRIPT, '--offline-fixture',
                        os.path.join(tempfile.gettempdir(), 'no-such-fixture-xyz.json')],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=60)
    both = (r.stdout or '') + (r.stderr or '')
    assert r.returncode == 2 and '读不到' in both and 'Traceback' not in both, (r.returncode, both[:200])
# —— 可执行面（本仓纪律：守卫只有被**真的执行**才算存在）——
# 为什么必须有这一段：CI 的两条腿都以 `python -X utf8 tests/<file>.py` 形态调用守卫——
#   · 腿 1c（`.github/workflows/bounty-board-check.yml`）：`for f in tests/test_*.py; do python -X utf8 "$f"`
#   · 腿 3c（`tests/run_mutation_guards.py`）：`python -X utf8 tests/<file>.py --mutate`
# 而本文件此前是**纯 pytest 风格**（只有 `def test_*`，无 `__main__`、无顶层 `sys.exit`）：
# 上述两条腿都只是把本模块 import 一遍、把 6 个函数对象建出来就退 0 ——
# **断言零求值、变异臂零触发，却恒报绿**（腿 3c 还打出 `[OK]`）。
# 本仓工作流头部点名过这个毛病（「有人写了、没人跑」），本段把它接线。
_ASSERTIONS = (test_clean_fixture_passes, test_repo_drift_warns,
               test_project_mismatch_fails, test_bad_difficulty_fails,
               test_p_severity_maps, test_no_marker_reports,
               test_bad_fixture_fails_closed, test_missing_fixture_fails_closed)

# 变异臂：锚点 → (原串, 短路串)
_ARMS = {
    'R1': ("errs.append('project=%s but target=%s implies %s'", "pass  # "),
    'R2': ("errs.append('difficulty=%r not in vocab", "pass  # "),
    # R3：把「畸形 fixture ⇒ rc=2」的守卫短路掉 ⇒ 新断言必须转红（否则判据空转）。
    # 锚点取整段 if，确保唯一命中。
    'R3': ("        if not isinstance(_doc, list):\n"
           "            print('::error::fixture 顶层不是数组：%s（实际 %s）'\n"
           "                  % (a.offline_fixture, type(_doc).__name__), file=sys.stderr)\n"
           "            sys.exit(2)\n", "        pass  #\n"),
}


def _run_assertions():
    """跑全部断言，返回失败条数（逐条 [PASS]/[FAIL] ＋ 汇总行）。"""
    fail = 0
    for fn in _ASSERTIONS:
        try:
            fn()
            print('[PASS] %s' % fn.__name__)
        except AssertionError as exc:
            print('[FAIL] %s  %s' % (fn.__name__, exc))
            fail += 1
    print('通过 %d / 失败 %d' % (len(_ASSERTIONS) - fail, fail))
    return fail


def _read_bytes(p):
    with io.open(p, 'rb') as fh:
        return fh.read()


def _write_bytes(p, b):
    # **字节级还原**：不能用文本模式 'w' 写回——Windows 下会把 \n 变 \r\n，
    # 与 `.gitattributes` 的 `eol=lf` 相冲 ⇒ 工作树被写脏，workflow 第 4 步
    # 「跑完不许把仓搞脏」即红。
    with io.open(p, 'wb') as fh:
        fh.write(b)


def _mutate(argv):
    """变异自证：逐条短路判据 ⇒ 对应断言**必须**转红（finally 还原，零残留）。"""
    want = ''
    for a in argv:
        if a == '--mutate':
            want = want or 'ALL'
        elif a.startswith('--mutate='):
            want = a.split('=', 1)[1]
    if not want:
        want = os.environ.get('MUTATE_TARGET', '')
    if not want:
        return 0

    print('— 反证：逐条短路判据 ⇒ 对应断言必须转红（否则判据空转）—')
    ids = sorted(_ARMS) if want == 'ALL' else [want]
    orig, red = _read_bytes(SCRIPT), 0
    try:
        for mid in ids:
            old, new = _ARMS[mid]
            text = orig.decode('utf-8')
            if text.count(old) != 1:
                print('[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）⇒ 无法变异，判据失效'
                      % (mid, text.count(old)))
                return 2
            _write_bytes(SCRIPT, text.replace(old, new).encode('utf-8'))
            if _run_assertions() == 0:
                print('[MUTATE-FAIL] %s：短路后断言仍全绿（判据空转）' % mid)
                red += 1
            else:
                print('[MUTATE-OK]   %s：短路后转红' % mid)
    finally:
        _write_bytes(SCRIPT, orig)
    print('反证结果：%d 条变异，%s' % (len(ids), '全部转红' if red == 0 else '%d 条未转红' % red))
    return 1 if red else 0


if __name__ == '__main__':
    _f = _run_assertions()
    _m = _mutate(sys.argv[1:])
    sys.exit(1 if (_f or _m) else 0)
