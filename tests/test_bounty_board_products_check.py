# -*- coding: utf-8 -*-
"""test_bounty_board_products_check.py · `bounty_board.py --products-check` 的四产物漂移闸

被修处（`scripts/bounty_board.py`）：
    四个导出分派（`--board-out` / `--value-vector-out` / `--promotion-out` / `--roles-out`）
    各自 `return 0`，**没有任何一条判据回头看盘上产物是否与「现渲染」一致**。
    ⇒ 改渲染/导出逻辑后，盘上已提交的
      `docs/bounty/{board.md,value_vector.json,promotion.json,roles.json}`
      会**静默陈旧**，而全仓无守卫会红。

    《运行手册》§四-1 自认的盲区正是这一类（「改生成器源没重生成产物」）；
    同仓 `review_build.py --check` 是**读盘比对**的既有体例。

本守卫四组：
  A 四产物与真源一致 ⇒ 退出 0 ＋「一致」
  B 篡改其一 ⇒ 退出 1 ＋ 点名该产物（含两侧字节数）
  C 产物缺失 ⇒ 退出 1 ＋ 点名「缺产物」
  D **反向证明**：把漂移分支短路后跑同一篡改产物 ⇒ **退出 0**（漏报）
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
_IMPL = os.path.join(_REPO, "scripts", "bounty_board.py")
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


PRODUCTS = ("board.md", "value_vector.json", "promotion.json", "roles.json")


def _mk():
    """把仓内四产物复制到一个临时目录（作为被检对象）。"""
    d = tempfile.mkdtemp(prefix="bb_products_")
    for n in PRODUCTS:
        shutil.copy2(os.path.join(_REPO, "docs", "bounty", n), os.path.join(d, n))
    return d


def _chk(d, impl=None):
    return subprocess.run([PY, "-X", "utf8", impl or _IMPL, "--ledger", _LEDGER,
                           "--products-check", d],
                          capture_output=True, text=True, encoding="utf-8", cwd=_REPO)


print('— A 四产物一致 ⇒ 退出 0 —')
d = _mk()
a = _chk(d)
check('A rc=0', a.returncode == 0, f'rc={a.returncode}')
check('A 输出含「四个产物与真源一致」', "四个产物与真源一致" in a.stdout, a.stdout.strip()[:64])

print('— B 篡改其一 ⇒ 退出 1 ＋ 点名 —')
with io.open(os.path.join(d, "roles.json"), "w", encoding="utf-8", newline="\n") as fh:
    fh.write('{"reviewer":["tamper"],"maintainer":[]}\n')
b = _chk(d)
check('B rc=1', b.returncode == 1, f'rc={b.returncode}')
check('B 点名 roles.json 漂移', "roles.json" in b.stderr and "漂移" in b.stderr,
      (b.stderr or "").strip().splitlines()[0][:64])

print('— C 产物缺失 ⇒ 退出 1 ＋ 点名 —')
d2 = _mk()
os.remove(os.path.join(d2, "board.md"))
c = _chk(d2)
check('C rc=1', c.returncode == 1, f'rc={c.returncode}')
check('C 点名「缺产物：board.md」', "缺产物" in c.stderr and "board.md" in c.stderr,
      (c.stderr or "").strip().splitlines()[0][:64])

print('— D 零行为变更：四个 --*-out 仍能正常导出 —')
d3 = tempfile.mkdtemp(prefix="bb_out_")
for flag, name in (("--board-out", "board.md"), ("--value-vector-out", "value_vector.json"),
                   ("--promotion-out", "promotion.json"), ("--roles-out", "roles.json")):
    r = subprocess.run([PY, "-X", "utf8", _IMPL, "--ledger", _LEDGER,
                        flag, os.path.join(d3, name)],
                       capture_output=True, text=True, encoding="utf-8", cwd=_REPO)
    check(f'D {flag} 仍 rc=0 且落盘',
          r.returncode == 0 and os.path.isfile(os.path.join(d3, name)), f'rc={r.returncode}')

print('— E 反向证明 —')
SRC = io.open(_IMPL, encoding="utf-8").read()
_BLK = '''                if _got != want[_path]:
                    drift.append("漂移：%s（盘上 %d 字节 ／ 现渲染 %d 字节）"
                                 % (_path, len(_got.encode("utf-8")),
                                    len(want[_path].encode("utf-8"))))'''
check('E0 漂移判据锚点命中', SRC.count(_BLK) == 1, f'命中 {SRC.count(_BLK)} 次')
if SRC.count(_BLK) == 1:
    op = os.path.join(_REPO, "scripts", "_bb_old_probe.py")
    io.open(op, "w", encoding="utf-8", newline="\n").write(SRC.replace(_BLK, "                pass", 1))
    try:
        o = _chk(d, impl=op)
        check('E 短路漂移判据后 ⇒ **退出 0**（漏报，证明本件有判别力）',
              o.returncode == 0, f'rc={o.returncode}')
    finally:
        if os.path.isfile(op):
            os.remove(op)

for x in (d, d2, d3):
    shutil.rmtree(x, ignore_errors=True)
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
