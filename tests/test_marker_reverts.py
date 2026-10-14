# -*- coding: utf-8 -*-
"""test_marker_reverts.py · 「静默回退」检查器的守卫

被覆盖的东西（`scripts/check_marker_reverts.py`）：
    `docs/bounty/运行手册_维护者长期任务_v0.1.md` §二 第 8 道（★看删除行）要求人工核对
    「`^-` 行里含**他人**留痕注释（`★本笔` / `★fix-`）⇒ 该笔在静默回退别人已合并的修复」，
    而 §七 明文承认：

    > 本手册是**流程描述**，不是判据：它本身**没有守卫**。若某轮跳过 §二 的某一道，
    > 不会有任何测试变红。**这是本手册当前的已知弱点**——补法是给关键步骤
    > （如「删除行检查」）**做成可跑脚本并纳入 CI**，而不是靠这份文本。

    本脚本即那个「可跑脚本」；本守卫是它的判据面。

五组：
  A 无回退 ⇒ 退出 0 ＋「未发现疑似静默回退」
  B 删掉含 `★本笔` 的行 ⇒ 退出 1 ＋ 点名文件与行号
  C `--json` 机读结构（含 hits 明细）
  D 坏 ref ⇒ 退出 2（fail-closed，**不抛裸栈**）
  E **反向证明**：把标记表换成不可能命中的串 ⇒ 同一 diff **退出 0**（漏报，
    证明本件的检出确实来自标记判据，而不是别的什么）
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
_IMPL = os.path.join(_REPO, "scripts", "check_marker_reverts.py")
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


def _impl(b):
    return subprocess.run([PY, "-X", "utf8", _IMPL, *b],
                          capture_output=True, text=True, encoding="utf-8", cwd=_REPO)


# ---------------------------------------------------------------- 搭一个临时仓
work = tempfile.mkdtemp(prefix="mr_repo_")
git(["init", "-q", "-b", "main"], work)
git(["config", "user.email", "t@t"], work)
git(["config", "user.name", "t"], work)

TARGET = os.path.join(work, "code.py")
io.open(TARGET, "w", encoding="utf-8", newline="\n").write(
    "# ★本笔：甲的修复 A\n"
    "A = 1\n"
    "# ★fix-：乙的修复 B\n"
    "B = 2\n"
    "# 普通注释\n"
    "C = 3\n")
git(["add", "-A"], work)
git(["commit", "-q", "-m", "base"], work)
git(["branch", "base"], work)   # 标注基线（不改名）

print('— A 无回退 ⇒ 退出 0 —')
a = _impl(["--base", "base", "--head", "base", "--repo", work])
check('A rc=0', a.returncode == 0, f'rc={a.returncode}')
check('A 输出含「未发现疑似静默回退」', "未发现疑似静默回退" in a.stdout, a.stdout.strip()[:60])

print('— B 删掉含留痕标记的行 ⇒ 退出 1 ＋ 点名 —')
io.open(TARGET, "w", encoding="utf-8", newline="\n").write(
    "A = 1\n"
    "B = 2\n"
    "# 普通注释\n"
    "C = 3\n")
git(["add", "-A"], work)
git(["commit", "-q", "-m", "head: 静默回退两条留痕"], work)
git(["branch", "head"], work)   # 标注头部（不改名）
b = _impl(["--base", "base", "--head", "head", "--repo", work])
check('B rc=1', b.returncode == 1, f'rc={b.returncode}')
check('B 点名 code.py', "code.py" in b.stderr, (b.stderr or "").strip().splitlines()[0][:64]
      if b.stderr.strip() else '')
check('B 报出 2 行', "2 行" in b.stderr, (b.stderr or "").strip().splitlines()[-1][:64])
check('B 两条标记都被认出', "★本笔" in b.stderr and "★fix-" in b.stderr, '')

print('— C --json 机读结构 —')
c = _impl(["--base", "base", "--head", "head", "--repo", work, "--json"])
check('C rc=1', c.returncode == 1, f'rc={c.returncode}')
try:
    doc = json.loads(c.stdout)
    check('C 结构含 hits / merge_base / markers',
          isinstance(doc.get("hits"), list) and "merge_base" in doc and doc.get("markers") == ["★本笔", "★fix-"],
          str(list(doc.keys())))
    check('C hits 有 2 条且带 path/line/text',
          len(doc["hits"]) == 2 and all(k in doc["hits"][0] for k in ("path", "line", "text")),
          json.dumps(doc["hits"][0], ensure_ascii=False)[:70])
except Exception as exc:
    check('C JSON 可解析', False, f'{type(exc).__name__}: {exc}')

print('— D 坏 ref ⇒ 退出 2（fail-closed，不抛裸栈）—')
d = _impl(["--base", "no-such-ref-zzz", "--head", "head", "--repo", work])
check('D rc=2', d.returncode == 2, f'rc={d.returncode}')
check('D 输出含 [error]', "[error]" in d.stderr, (d.stderr or "").strip()[:60])
check('D **无 Traceback**', "Traceback" not in d.stderr, '')

print('— E 反向证明：换掉标记表 ⇒ 同一 diff 退出 0（漏报）—')
e = _impl(["--base", "base", "--head", "head", "--repo", work,
           "--markers", "@@NOSUCHMARKER@@"])
check('E 换成不可能命中的标记 ⇒ **rc=0**（证明检出确实来自标记判据）',
      e.returncode == 0, f'rc={e.returncode}')

print('— F 静态面：手册 §七 点名要求「做成可跑脚本」—')
SRC = io.open(_IMPL, encoding="utf-8").read()
check('F0 标记表含两种留痕形态', '★本笔' in SRC and '★fix-' in SRC, '')
check('F 脚本 docstring 引了手册 §二-8 与 §七（可追溯要求来源）',
      "§二" in SRC and "§七" in SRC, '')
check('F 退出码契约写在 docstring 里', "`0` = 未发现" in SRC or "0` = 未发现" in SRC, '')

shutil.rmtree(work, ignore_errors=True)
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
