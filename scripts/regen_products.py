#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵枢悬赏板 · 产物重生成单一入口。

为什么需要（本仓已发生过的失效形态）：
  产物有 8 件（board / value_vector / promotion / roles / site / 贡献表 / 贡献总表 / 悬赏清单），
  但**没有任何统一入口**。维护者只能在临时脚本里手抄一份命令清单，于是：
    · 漏一件 -> 该产物静默陈旧（check 抓不到，因为没人跑）；
    · 抄错参数 -> 若目标脚本静默忽略未知参数，还会**照写默认产物并报成功**
      （2026-10-24 实证：`bounty_list.py --write` 一直不被接受，但 #1655 之前
       静默忽略 + 照写，日志恒为 rc=0；#1655 改成点名 rc=2 后才暴露）。

  本脚本把「有哪些产物、各用什么命令、生成后落在哪个路径」收敛成**一份 STEPS 表**，
  并配 `tests/test_regen_products.py` 断言「每步 rc=0 且跑完工作树干净」。

用法：
  python -X utf8 scripts/regen_products.py --dry-run   # 只打印将执行的命令
  python -X utf8 scripts/regen_products.py             # 真跑
  python -X utf8 scripts/regen_products.py --verify    # 真跑 + 账本不变量 + 产物新鲜度闸

不适用条件：
  不判产物内容是否正确（那是各生成器自己的守卫）；只判「命令能跑通、产物被写出」。
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LEDGER = 'docs/bounty/ledger.json'

#: (名字, argv 后缀, 产物相对路径；目录以 / 结尾)
STEPS = (
    ('board', ['scripts/bounty_board.py', '--ledger', LEDGER, '--board-out', 'docs/bounty/board.md'],
     'docs/bounty/board.md'),
    ('value_vector', ['scripts/bounty_board.py', '--ledger', LEDGER,
                      '--value-vector-out', 'docs/bounty/value_vector.json'],
     'docs/bounty/value_vector.json'),
    ('promotion', ['scripts/bounty_board.py', '--ledger', LEDGER,
                   '--promotion-out', 'docs/bounty/promotion.json'],
     'docs/bounty/promotion.json'),
    ('roles', ['scripts/bounty_board.py', '--ledger', LEDGER,
               '--roles-out', 'docs/bounty/roles.json'],
     'docs/bounty/roles.json'),
    ('site', ['scripts/build_site.py', '--ledger', LEDGER, '--out', 'site'], 'site/'),
    ('daily_table', ['scripts/daily_table.py', '--ledger', LEDGER, '--out', 'docs/bounty/贡献表.md'],
     'docs/bounty/贡献表.md'),
    ('monthly_summary', ['scripts/monthly_summary.py', '--ledger', LEDGER,
                         '--out', 'docs/bounty/贡献总表.md'],
     'docs/bounty/贡献总表.md'),
    # 注意：bounty_list.py 只认 --check / --stdout；**不带参数才是写盘**。
    # 不要写 --write —— 那是 2026-10-24 踩过的坑（旧版静默忽略，新版 rc=2）。
    ('bounty_list', ['scripts/bounty_list.py'], 'docs/bounty/悬赏清单.md'),
)


def _run(argv, cwd, timeout=600):
    return subprocess.run([PY, '-X', 'utf8'] + argv, cwd=cwd, capture_output=True,
                          text=True, encoding='utf-8', errors='replace', timeout=timeout)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='只打印命令，不执行')
    ap.add_argument('--verify', action='store_true', help='跑完再校验不变量与产物新鲜度')
    ap.add_argument('--root', default=ROOT)
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    missing = []
    for name, tail, product in STEPS:
        script = os.path.join(root, tail[0])
        if not os.path.isfile(script):
            missing.append('%s: 缺脚本 %s' % (name, tail[0]))
    if missing:
        for m in missing:
            print('::error::' + m)
        return 2

    if args.dry_run:
        for name, tail, product in STEPS:
            print('%-16s python -X utf8 %s   -> %s' % (name, ' '.join(tail), product))
        print('共 %d 步' % len(STEPS))
        return 0

    failed = []
    for name, tail, product in STEPS:
        p = _run(tail, root)
        ok = (p.returncode == 0)
        last = ((p.stdout or '').strip().splitlines() or [''])[-1]
        print('[%s] %-16s rc=%d  %s' % ('OK' if ok else 'FAIL', name, p.returncode, last[:110]))
        if not ok:
            err = ((p.stderr or '').strip().splitlines() or [''])[-1]
            print('        stderr: ' + err[:160])
            failed.append(name)
            continue
        exists = (os.path.isdir(os.path.join(root, product)) if product.endswith('/')
                  else os.path.isfile(os.path.join(root, product)))
        if not exists:
            print('::error::%s 声称成功但产物不存在：%s' % (name, product))
            failed.append(name)

    if args.verify:
        for label, tail in (
            ('不变量', ['scripts/check_ledger_invariants.py', '--quiet']),
            ('产物新鲜度', ['tests/test_products_fresh.py']),
        ):
            p = _run(tail, root, timeout=600)
            print('[%s] %-16s rc=%d' % ('OK' if p.returncode == 0 else 'FAIL', label, p.returncode))
            if p.returncode != 0:
                failed.append(label)

    print()
    if failed:
        print('失败 %d 项：%r' % (len(failed), failed))
        return 1
    print('全部 %d 步成功' % len(STEPS))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
