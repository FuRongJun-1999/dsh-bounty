#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产物新鲜度守卫：把三条「读盘漂移闸」接进**真仓**判据面。

为什么需要（本仓已发生过的失效形态）：
  `bounty_list.py --check` / `daily_table.py --check --out` / `build_site.py --check`
  三条闸都实现了「盘上产物 vs 现渲染」，但它们各自的守卫
  （`tests/test_bounty_list.py`、`tests/test_daily_table_check_drift.py`）
  全在**临时沙箱**里跑合成数据 —— **没有一条判据对着真仓已提交的产物**。

  于是最常见的漂移「改了渲染逻辑 / 追加了账本事件，忘了重新生成，把旧产物一起提交」
  全套守卫照样全绿。实测（2026-10-23）：把 `docs/bounty/悬赏清单.md`、
  `docs/bounty/贡献表.md`、`site/honor.html` 各追加一行注释并**提交**（工作树干净），
  `for f in tests/test_*.py; do python -X utf8 "$f"; done` ⇒ **59 件 59/0**，
  而三条闸单独跑各自 rc=1。

判据：
  对真仓逐条跑三条闸，任一 rc≠0 ⇒ 点红并点名是哪一件（可 grep）。

不适用条件：
  不判「闸本身的实现对不对」（那是各闸自己的守卫）；也不判产物内容是否**正确**
  —— 只判「盘上 == 现渲染」，即不陈旧。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: (名字, 命令, 该闸覆盖的产物路径)
GATES = (
    ("bounty_list", [sys.executable, "-X", "utf8", "scripts/bounty_list.py", "--check"],
     "docs/bounty/悬赏清单.md"),
    ("daily_table", [sys.executable, "-X", "utf8", "scripts/daily_table.py",
                     "--check", "--out", "docs/bounty/贡献表.md"],
     "docs/bounty/贡献表.md"),
    ("build_site", [sys.executable, "-X", "utf8", "scripts/build_site.py", "--check"],
     "site/"),
)

PASSED = []
FAILED = []


def check(name, ok, detail=''):
    (PASSED if ok else FAILED).append((name, detail))
    print('[%s] %s%s' % ('PASS' if ok else 'FAIL', name, ('  <- ' + detail) if detail else ''))


def run_gate(cmd):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=180)
    out = ((p.stdout or '') + (p.stderr or '')).strip().splitlines()
    return p.returncode, (out[-1] if out else '')


def main():
    for name, cmd, product in GATES:
        exists = (os.path.isdir(os.path.join(ROOT, product)) if product.endswith('/')
                  else os.path.isfile(os.path.join(ROOT, product)))
        check('%s 产物存在（缺文件不得静默跳过）' % name, exists, product)
        rc, last = run_gate(cmd)
        check('%s 盘上产物与现渲染一致（不陈旧）' % name, rc == 0, 'rc=%d %s' % (rc, last[:90]))
    print()
    print('通过 %d / 失败 %d' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
