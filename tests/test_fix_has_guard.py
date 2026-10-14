# -*- coding: utf-8 -*-
"""test_fix_has_guard.py · 「修复有没有守卫」检查器的守卫

被覆盖的东西（`scripts/check_fix_has_guard.py`）：
    `docs/bounty/运行手册_维护者长期任务_v0.1.md` §八（2026-10-14 实证第 2 条）：

    > **修复类 PR 可能「零守卫」**：只改 `scripts/` 不改 `tests/` 的修复，合并后**没有任何
    > 守卫拦得住它的回归**。判据：`git diff --name-only` 里没有 `tests/` 路径。
    > 处置：修复正确 ＋ 回归绿 ⇒ 照合，但**回执里必须写明缺口**……

    而 §七 承认手册自身没有守卫，要求把关键步骤**做成可跑脚本**。

五组：
  A 只改 `scripts/`（零守卫）⇒ 退出 1 ＋ 列出实现文件
  B `scripts/` + `tests/` 都改 ⇒ 退出 0
  C 只改文档（无实现面）⇒ 退出 0（不误报）
  D `--json` 结构 ＋ `--similar` 的「既有缺口」分支
  E **反向证明**：把实现面目录表清空（模拟「判据失效」）⇒ 同一零守卫 diff **退出 0**（漏报）
"""
import sys
import os
import io
import json
import shutil
import subprocess
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "check_fix_has_guard.py")
PY = sys.executable

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


def git(args, cwd):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd)


def _impl(b, impl=None):
    return subprocess.run([PY, "-X", "utf8", impl or _IMPL, *b],
                          capture_output=True, text=True, encoding="utf-8", cwd=_REPO)


work = tempfile.mkdtemp(prefix="fhg_repo_")
git(["init", "-q", "-b", "main"], work)
git(["config", "user.email", "t@t"], work)
git(["config", "user.name", "t"], work)
os.makedirs(os.path.join(work, "scripts"), exist_ok=True)
os.makedirs(os.path.join(work, "tests"), exist_ok=True)
os.makedirs(os.path.join(work, "docs"), exist_ok=True)
io.open(os.path.join(work, "scripts", "code.py"), "w", encoding="utf-8", newline="\n").write("X = 1\n")
io.open(os.path.join(work, "tests", "test_code.py"), "w", encoding="utf-8", newline="\n").write("# 基线测试（故意不引用任何被检符号）\n")
io.open(os.path.join(work, "docs", "readme.md"), "w", encoding="utf-8", newline="\n").write("doc\n")
git(["add", "-A"], work)
git(["commit", "-q", "-m", "base"], work)
git(["branch", "base"], work)

print('— A 只改 scripts/（零守卫）⇒ 退出 1 —')
io.open(os.path.join(work, "scripts", "code.py"), "w", encoding="utf-8", newline="\n").write("X = 2\n")
git(["add", "-A"], work)
git(["commit", "-q", "-m", "fix without guard"], work)
git(["branch", "gap"], work)
a = _impl(["--base", "base", "--head", "gap", "--repo", work])
check('A rc=1', a.returncode == 1, f'rc={a.returncode}')
check('A 输出含「零守卫」', "零守卫" in a.stderr, (a.stderr or "").strip().splitlines()[0][:62])
check('A 列出实现文件 scripts/code.py', "scripts/code.py" in a.stderr, '')

print('— B scripts/ + tests/ 都改 ⇒ 退出 0 —')
git(["checkout", "-q", "-b", "ok", "base"], work)
io.open(os.path.join(work, "scripts", "code.py"), "w", encoding="utf-8", newline="\n").write("X = 3\n")
io.open(os.path.join(work, "tests", "test_code.py"), "w", encoding="utf-8", newline="\n").write("assert True\n")
git(["add", "-A"], work)
git(["commit", "-q", "-m", "fix with guard"], work)
b = _impl(["--base", "base", "--head", "ok", "--repo", work])
check('B rc=0', b.returncode == 0, f'rc={b.returncode}')
check('B 输出说「都改了」', "守卫面都改了" in b.stdout or "都改了" in b.stdout, b.stdout.strip()[:62])

print('— C 只改文档（无实现面）⇒ 退出 0（不误报）—')
git(["checkout", "-q", "-b", "doc", "base"], work)
io.open(os.path.join(work, "docs", "readme.md"), "w", encoding="utf-8", newline="\n").write("doc2\n")
git(["add", "-A"], work)
git(["commit", "-q", "-m", "docs only"], work)
c = _impl(["--base", "base", "--head", "doc", "--repo", work])
check('C rc=0', c.returncode == 0, f'rc={c.returncode}')
check('C 输出含「未见实现面改动」', "未见实现面改动" in c.stdout, c.stdout.strip()[:62])

print('— D --json 结构 ＋ --similar 既有缺口分支 —')
git(["checkout", "-q", "gap"], work)
d = _impl(["--base", "base", "--head", "gap", "--repo", work, "--json", "--similar", "_NEVER_IN_TESTS"])
check('D rc=1', d.returncode == 1, f'rc={d.returncode}')
try:
    doc = json.loads(d.stdout)
    check('D 结构含 missing_guard / impl / tests / changed',
          doc.get("missing_guard") is True and doc.get("impl") == ["scripts/code.py"]
          and doc.get("tests") == [] and "changed" in doc,
          json.dumps({k: doc.get(k) for k in ("impl", "tests", "missing_guard")}, ensure_ascii=False)[:70])
    check('D --similar：_NEVER_IN_TESTS 在 tests/ 下 0 次 ⇒ similar_absent_in_tests=True',
          doc.get("similar_absent_in_tests") is True, str(doc.get("similar_absent_in_tests")))
except Exception as exc:
    check('D JSON 可解析', False, f'{type(exc).__name__}: {exc}')

print('— E 反向证明：清空实现面目录表 ⇒ 同一零守卫 diff 退出 0（漏报）—')
SRC = io.open(_IMPL, encoding="utf-8").read()
_OLD = SRC.replace('IMPL_DIRS = ("scripts/",)', 'IMPL_DIRS = ()', 1)
check('E0 还原锚点命中', _OLD != SRC, '')
if _OLD != SRC:
    op = os.path.join(_REPO, "scripts", "_fhg_old_probe.py")
    io.open(op, "w", encoding="utf-8", newline="\n").write(_OLD)
    try:
        e = _impl(["--base", "base", "--head", "gap", "--repo", work], impl=op)
        check('E 判据失效后 ⇒ **退出 0**（漏报，证明本件有判别力）', e.returncode == 0, f'rc={e.returncode}')
    finally:
        if os.path.isfile(op):
            os.remove(op)

print('— F 静态面：docstring 引了 §八-2 与 §七 —')
check('F0 含「零守卫」判据说明', "零守卫" in SRC, '')
check('F docstring 引了 §八 与 §七', "§八" in SRC and "§七" in SRC, '')
check('F 退出码契约在位', "`0` = 未见" in SRC or "0` = 未见" in SRC, '')

shutil.rmtree(work, ignore_errors=True)
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
