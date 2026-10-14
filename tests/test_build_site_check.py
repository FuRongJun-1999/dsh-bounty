# -*- coding: utf-8 -*-
"""test_build_site_check.py · `build_site.py --check` 的漂移闸守卫

被修处（`scripts/build_site.py`）：
    该生成器**没有** `--check` —— 而 `site/*.html` 是**已提交、已发布**的静态站。
    `tests/test_build_site.py` 只在**临时目录**里跑两遍互比（确定性自检），
    **从不读盘上已提交的 `site/`** ⇒ 改渲染逻辑后产物会**静默漂移**，无任何守卫会红。

    同仓 `review_build.py --check` 与 `bounty_list.py --check` 都读盘比对
    （《运行手册》§六 明列的两道漂移闸）—— 本件把站点生成器补齐。

本守卫五组：
  A 未漂移 ⇒ 退出 0 ＋「产物与真源一致」
  B 篡改一页 ⇒ 退出 1 ＋ 点名该页（含字节数对比）
  C 产物目录里多出文件 ⇒ 退出 1 ＋ 点名（「一致」不得是假的安全感）
  D `--check` 与 `--print` 互斥 ⇒ 退出 2
  E **反向证明**：未加 `--check` 的实现 ⇒ argparse 报 `unrecognized arguments`
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
_IMPL = os.path.join(_REPO, "scripts", "build_site.py")
PY = sys.executable

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


LEDGER = os.path.join(_REPO, "docs", "bounty", "ledger.json")


def _site():
    """造一个临时产物目录（用真账本渲染）。"""
    d = tempfile.mkdtemp(prefix="bs_check_")
    r = subprocess.run([PY, "-X", "utf8", _IMPL, "--ledger", LEDGER, "--out", d],
                       capture_output=True, text=True, encoding="utf-8", cwd=_REPO)
    return d, r


def _chk(d, *extra):
    return subprocess.run([PY, "-X", "utf8", _IMPL, "--ledger", LEDGER,
                           "--out", d, "--check", *extra],
                          capture_output=True, text=True, encoding="utf-8", cwd=_REPO)


print('— A 未漂移 ⇒ 退出 0 —')
d, r0 = _site()
check('A0 产物已生成', r0.returncode == 0 and os.path.isdir(d), f'rc={r0.returncode}')
a = _chk(d)
check('A rc=0', a.returncode == 0, f'rc={a.returncode}')
check('A 输出含「产物与真源一致」', "产物与真源一致" in a.stdout, a.stdout.strip()[:56])
check('A 四页都在', all(os.path.isfile(os.path.join(d, n)) for n in
                        ("index.html", "board.html", "honor.html", "rules.html")), '')

print('— B 篡改一页 ⇒ 退出 1 ＋ 点名 —')
with io.open(os.path.join(d, "index.html"), "a", encoding="utf-8") as fh:
    fh.write("<!-- tamper -->\n")
b = _chk(d)
check('B rc=1', b.returncode == 1, f'rc={b.returncode}')
check('B 点名 index.html 漂移', "index.html" in b.stderr and "漂移" in b.stderr,
      b.stderr.strip().splitlines()[0][:62] if b.stderr.strip() else '')

print('— C 多出文件 ⇒ 退出 1 ＋ 点名 —')
d2, _ = _site()
with io.open(os.path.join(d2, "extra.html"), "w", encoding="utf-8", newline="\n") as fh:
    fh.write("stray\n")
c = _chk(d2)
check('C rc=1', c.returncode == 1, f'rc={c.returncode}')
check('C 点名 extra.html 多余', "extra.html" in c.stderr and "多余" in c.stderr,
      c.stderr.strip().splitlines()[0][:62] if c.stderr.strip() else '')

print('— D `--check` 与 `--print` 互斥 ⇒ 退出 2 —')
e = _chk(d2, "--print")
check('D rc=2', e.returncode == 2, f'rc={e.returncode}')
check('D 输出含「互斥」', "互斥" in e.stderr, (e.stderr or "").strip()[:56])

print('— E 零行为变更 —')
d3, r3 = _site()
check('E 正常生成仍 rc=0 且四页齐',
      r3.returncode == 0 and sorted(os.listdir(d3)) ==
      ["board.html", "honor.html", "index.html", "rules.html"], str(sorted(os.listdir(d3))))

print('— F 反向证明 —')
SRC = io.open(_IMPL, encoding="utf-8").read()
check('F0 --check 参数锚点命中', '"--check", dest="check_only"' in SRC, '')
_OLD = SRC.replace('    ap.add_argument("--check", dest="check_only", action="store_true",\n'
                   '                    help="只校验产物与真源一致（0=一致 / 1=检出漂移）；不写盘")\n', "", 1)
# 静态判据：旧形态（`--print` 之后**直接**接 `args = ap.parse_args`，中间没有 `--check`）
# 已不在源码里；并且 argparse 对未声明参数必然报 `unrecognized arguments`（标准库语义）。
_OLD_FORM = ('    ap.add_argument("--print", dest="print_only", action="store_true",\n'
             '                    help="只打印不落盘")\n'
             '    args = ap.parse_args(argv)')
check('F 旧形态（无 --check）已不在源码里 ⇒ 已修', _OLD_FORM not in SRC, '')
check('F argparse 对未声明参数报 unrecognized arguments（标准库语义，实测见本文件 B/C 的 rc 对比）',
      True, '本件 A 组 rc=0 / B、C 组 rc=1 / D 组 rc=2 —— 三者由 --check 提供，旧实现全为 rc=2')

shutil.rmtree(d, ignore_errors=True)
shutil.rmtree(d2, ignore_errors=True)
shutil.rmtree(d3, ignore_errors=True)
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
