#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产物重生成入口守卫：每条命令真的能跑通 + 幂等 + 覆盖齐全。

为什么需要（本仓已发生过的失效形态）：
  2026-10-24 实证：维护侧的批量结算脚本手抄了一份 8 步 gen 清单，其中第 8 步写的是
  `bounty_list.py --write` —— 而该脚本**只认 --check / --stdout，不带参数才是写盘**。
  因为旧版对未知参数**静默忽略并照写默认产物**，这一步一直报 rc=0，
  错误永久隐身，直到 #1655 把「未知参数」改成点名 rc=2 才第一次暴露。

  本守卫把「每一步真能跑通」变成可执行断言：任何一步 argv 写错（参数不被接受）
  都会立刻 rc≠0 并点名，而不是靠人眼看日志。

断言：
  A1 dry-run 列出的步数 == STEPS 长度，且每步脚本文件都存在。
  A2 全部调用都是 argv 列表（无字符串拼接、无 shell=True）——第 15 条口径。
  A3 真跑：每一步 rc==0，且它声称的产物路径确实存在。
  A4 幂等：跑完**已跟踪文件**零改动（新增未跟踪文件不算脏）。
  A5 覆盖：tests/test_products_fresh.py 关心的三件产物必须都在 STEPS 里
     （否则新鲜度闸与重生成入口会各管一摊，出现「闸知道某产物、入口不知道」的缺口）。

不适用条件：
  不判产物内容是否正确（各生成器自己的守卫管那个）；
  也不自动发现「新写了一个生成器但没登记进 STEPS」——需人工登记，
  本守卫只能保证**已登记的**都是对的、且与新鲜度闸不脱节。
"""
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import regen_products as rp  # noqa: E402

PASSED = []
FAILED = []


def check(name, ok, detail=''):
    (PASSED if ok else FAILED).append((name, detail))
    print('[%s] %s%s' % ('PASS' if ok else 'FAIL', name, ('  <- ' + detail) if detail else ''))


def sh(argv, to=600):
    return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=to)


def main():
    steps = rp.STEPS

    # ---- A1 dry-run 步数与脚本存在 ----
    p = sh([sys.executable, '-X', 'utf8', 'scripts/regen_products.py', '--dry-run'], to=180)
    out = (p.stdout or '')
    listed = len([l for l in out.splitlines() if l.startswith('python') is False and ' -> ' in l])
    check('A1 dry-run 正常退出', p.returncode == 0, 'rc=%d' % p.returncode)
    check('A1 dry-run 步数 == STEPS 长度', listed == len(steps),
          'listed=%d steps=%d' % (listed, len(steps)))
    miss = [t[0] for t in steps if not os.path.isfile(os.path.join(ROOT, t[1][0]))]
    check('A1b 每步脚本文件都存在', not miss, 'missing=%r' % miss)

    # ---- A2 全部是 argv 列表 ----
    bad = [t[0] for t in steps if not isinstance(t[1], (list, tuple))
           or not all(isinstance(x, str) for x in t[1])]
    check('A2 每步 argv 都是字符串列表（不过 shell）', not bad, 'bad=%r' % bad)

    # ---- A3 真跑：每步 rc==0 且产物存在 ----
    #  先给「已跟踪脏文件」拍快照，跑完只比**新增**的脏项 —— 否则开发中带未提交改动时
    #  会把既有改动误判成「重生成不幂等」。
    g0 = sh(['git', 'status', '--porcelain'], to=120)
    dirty_before = {l for l in (g0.stdout or '').splitlines()
                    if l.strip() and not l.startswith('??')}
    p = sh([sys.executable, '-X', 'utf8', 'scripts/regen_products.py'], to=900)
    o = p.stdout or ''
    fails = re.findall(r'^\\[FAIL\\]\\s+(\\S+)', o, re.M)
    check('A3 重生成全部成功（无 [FAIL] 步）', p.returncode == 0 and not fails,
          'rc=%d fails=%r' % (p.returncode, fails[:5]))
    absent = []
    for name, tail, product in steps:
        ap = os.path.join(ROOT, product)
        ok = os.path.isdir(ap) if product.endswith('/') else os.path.isfile(ap)
        if not ok:
            absent.append('%s:%s' % (name, product))
    check('A3b 每步声称的产物确实存在', not absent, 'absent=%r' % absent[:5])

    # ---- A4 幂等：跑完**不新增**已跟踪脏项（相对跑前快照） ----
    g = sh(['git', 'status', '--porcelain'], to=120)
    dirty_after = {l for l in (g.stdout or '').splitlines()
                   if l.strip() and not l.startswith('??')}
    added = sorted(dirty_after - dirty_before)
    check('A4 跑完未新增已跟踪脏项（幂等）', not added,
          '新增=%r（跑前已有 %d 项，属未提交改动，不计）' % (added[:5], len(dirty_before)))

    # ---- A5 与新鲜度闸覆盖不脱节 ----
    tp = os.path.join(ROOT, 'tests', 'test_products_fresh.py')
    need = []
    if os.path.isfile(tp):
        src = io.open(tp, encoding='utf-8').read()
        for m in re.finditer(r'"(docs/bounty/[^"]+)"', src):
            need.append(m.group(1))
    products = {t[2] for t in steps}
    gap = [x for x in need if x not in products]
    check('A5 新鲜度闸关心的产物都在 STEPS 里', not gap,
          'need=%r gap=%r' % (sorted(set(need)), gap))

    # ---- A6 单步超时：点名 rc=124 且记入 failed，不得 TimeoutExpired 裸栈 ----
    #  dsh-bounty #1729 / F26-04：原先任一步超 600s 即裸栈退出，且**记不进 failed**
    #  —— 与本脚本「每步都点名」的口径自相矛盾。
    slow = os.path.join(ROOT, 'scripts', '_slow_probe_tmp.py')
    io.open(slow, 'w', encoding='utf-8', newline='\n').write('import time\ntime.sleep(30)\n')
    real_run = rp._run
    old_steps = rp.STEPS

    def _quick(argv, cwd, timeout=600):
        return real_run(argv, cwd, timeout=0.2)   # 走真实 _run 的 try/except

    try:
        rp.STEPS = (('slow', ['scripts/_slow_probe_tmp.py'], 'none.md'),)
        rp._run = _quick
        import contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):   # 屏蔽被调 main() 的打印，免得误导读者
                rc = rp.main(['--root', ROOT])
            crashed = False
            rc_val = rc
        except Exception as ex:  # noqa: BLE001 —— 裸栈就是失败，要能被点名
            crashed = True
            rc_val = '%s: %s' % (type(ex).__name__, ex)
    finally:
        rp.STEPS = old_steps
        rp._run = real_run
        if os.path.isfile(slow):
            os.remove(slow)

    check('A6 单步超时：记入 failed 并返回 1（不抛 TimeoutExpired）',
          (not crashed) and rc_val == 1, 'crashed=%r rc=%r' % (crashed, rc_val))

    print()
    print('通过 %d / 失败 %d' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
