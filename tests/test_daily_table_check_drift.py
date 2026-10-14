# -*- coding: utf-8 -*-
"""test_daily_table_check_drift.py · `daily_table.py --check` 的**读盘漂移**判据

被修处（`scripts/daily_table.py`）：
    旧 `--check` **只做「渲染两遍互比」** —— 那是**确定性**，不是**漂移**。
    改 `render()` 的渲染逻辑后，盘上已提交的 `docs/bounty/贡献表.md` 会**静默陈旧**，
    而 `--check` 自己不会红、`tests/test_daily_table.py` 的断言又全在**合成账本**上跑
    ⇒ 源与产物漂移**无任何守卫拦得住**。

    **这正是《运行手册》§四-1 自认的盲区**（原文点名了本函数的 `--check` 与那份测试：
    「`daily_table.py --check` 只做「渲染两遍互比」（确定性自检）……**没有一条读盘上产物**
    ⇒ 源与产物漂移**无任何守卫会红**」）。

本守卫四组：
  A 产物与真源一致 ⇒ 退出 0 ＋「一致」
  B 篡改盘上产物 ⇒ 退出 1 ＋ 点名「产物漂移」
  C **向后兼容**：不给 `--out` ⇒ 行为与旧版逐位一致（只做确定性自检）
  D **反向证明**：把「漂移即 return 1」那两行去掉后跑同一篡改产物 ⇒ **退出 0**（漏报）
"""
import sys
import os
import io
import shutil
import subprocess
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "daily_table.py")
_LEDGER = os.path.join(_REPO, "docs", "bounty", "ledger.json")
PY = sys.executable

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


def _gen(out):
    return subprocess.run([PY, "-X", "utf8", _IMPL, "--ledger", _LEDGER, "--out", out],
                          capture_output=True, text=True, encoding="utf-8", cwd=_REPO)


def _chk(out=None, impl=None):
    a = [PY, "-X", "utf8", impl or _IMPL, "--ledger", _LEDGER, "--check"]
    if out:
        a += ["--out", out]
    return subprocess.run(a, capture_output=True, text=True, encoding="utf-8", cwd=_REPO)


d = tempfile.mkdtemp(prefix="dt_drift_")
out = os.path.join(d, "贡献表.md")

print('— A 产物与真源一致 ⇒ 退出 0 —')
check('A0 产物已生成', _gen(out).returncode == 0 and os.path.isfile(out), '')
a = _chk(out)
check('A rc=0', a.returncode == 0, f'rc={a.returncode}')
check('A 输出含「一致」', "一致" in a.stdout, a.stdout.strip()[:60])

print('— B 篡改盘上产物 ⇒ 退出 1 ＋ 点名 —')
with io.open(out, "a", encoding="utf-8") as fh:
    fh.write("\n<!-- tamper -->\n")
b = _chk(out)
check('B rc=1', b.returncode == 1, f'rc={b.returncode}')
check('B 点名「产物漂移」', "产物漂移" in b.stderr, (b.stderr or "").strip()[:64])

print('— C 向后兼容：不给 --out ⇒ 只做确定性自检 —')
c = _chk(None)
check('C rc=0（与旧版一致）', c.returncode == 0, f'rc={c.returncode}')
check('C 输出含「确定性自检通过」', "确定性自检通过" in c.stdout, c.stdout.strip()[:56])
check('C 输出**不含**「产物漂移」', "产物漂移" not in (c.stdout + c.stderr), '')

print('— D 反向证明 —')
SRC = io.open(_IMPL, encoding="utf-8").read()
_BLOCK = '''                if got != text:
                    print("产物漂移：%s（盘上 %d 字节 ／ 现渲染 %d 字节）"
                          % (args.out, len(got.encode("utf-8")), len(text.encode("utf-8"))),
                          file=sys.stderr)
                    return 1'''
check('D0 漂移判据锚点命中', SRC.count(_BLOCK) == 1, f'命中 {SRC.count(_BLOCK)} 次')
if SRC.count(_BLOCK) == 1:
    # 放回 scripts/ 下，复用它原有的 import 面（daily_table 自己 sys.path 处理好）
    op = os.path.join(_REPO, "scripts", "_dt_old_probe.py")
    io.open(op, "w", encoding="utf-8", newline="\n").write(
        SRC.replace(_BLOCK, "                pass", 1))
    try:
        o = _chk(out, impl=op)
        check('D 去掉漂移判据后 ⇒ **退出 0**（漏报，证明本件有判别力）',
              o.returncode == 0, f'rc={o.returncode}')
    finally:
        if os.path.isfile(op):
            os.remove(op)

shutil.rmtree(d, ignore_errors=True)
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
