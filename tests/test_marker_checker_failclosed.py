# -*- coding: utf-8 -*-
"""守卫：「无牙齿的闸」不得退 0 —— 标记表为空 ／ 错误归因

维护手册 §七 原文：本手册是**流程描述，不是判据**……**这是本手册当前的已知弱点**。
本件把两种「闸门静默失效」形态钉死（都属 §七 想消灭的那类：判据在，**牙不在**）：

  ① `--markers` 取值 strip 后为空（`" "` / `","` / `" , "`）⇒ 旧行为 `MARKERS = ()`
     ⇒ `any(mk in body for mk in ())` 恒 False ⇒ **报告「未发现疑似静默回退」并退 0**：
     闸门从「有牙齿」静默降级为**橡皮章**（0 检查 ≠ 通过）。新行为：输入错误 ⇒ 退 2，
     与 docstring 的退出码契约「2 = 输入/环境错误」逐字一致。
  ② `--repo` 指向无效目录 ⇒ 旧文案把原因写成「调不起 git（未安装或不在 PATH？）」，
     而实测真因是 `NotADirectoryError`（WinError 267）⇒ 错误归因会把排查引偏。
     新行为：按真实原因分述（git 缺席 ／ 仓目录无效·无权限）。

**反向对照**（防止「为了退 2 而把所有调用都判错」这种过度收紧）：
不传 `--markers`、或传非空标记表 ⇒ 行为**不变**（空 diff 仍退 0 并打印「未发现」）。
"""
import sys, os, subprocess
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


def py(args, cwd=None):
    r = subprocess.run([sys.executable, "-X", "utf8"] + args, cwd=cwd or _REPO,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"), timeout=180)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


MR = os.path.join("scripts", "check_marker_reverts.py")
GH = os.path.join("scripts", "check_fix_has_guard.py")
#: 不依赖 origin/main（CI 里未必有）⇒ 用 HEAD..HEAD 的空 diff，结论确定
SAME = ["--base", "HEAD", "--head", "HEAD"]

# ── ① 空标记表 ⇒ fail-closed（不得退 0） ────────────────────────────────────
print('— ① --markers 解析后为空 ⇒ 必须退 2（不得打印「未发现」）—')
for val in (" ", ",", " , "):
    rc, out = py([MR] + SAME + ["--markers", val])
    check('--markers %r ⇒ 退 2' % val, rc == 2, "rc=%s" % rc)
    check('--markers %r ⇒ 说明「标记表为空」' % val, "标记表为空" in out, out.strip()[:80])
    check('--markers %r ⇒ 不得输出「未发现疑似静默回退」' % val,
          "未发现疑似静默回退" not in out)

# ── ② 反向对照：有牙齿时行为不变 ───────────────────────────────────────────
print('— ② 反向对照：非空标记表 ／ 默认调用 ⇒ 照常退 0 —')
rc, out = py([MR] + SAME + ["--markers", "★本笔"])
check('--markers ★本笔 ⇒ 退 0（空 diff 无命中）', rc == 0, "rc=%s" % rc)
rc, out = py([MR] + SAME)
check('默认标记表 ⇒ 退 0（空 diff 无命中）', rc == 0, "rc=%s" % rc)
check('默认标记表 ⇒ 照常打印「未发现」', "未发现疑似静默回退" in out, out.strip()[:80])
rc, out = py([GH] + SAME)
check('check_fix_has_guard 空 diff ⇒ 退 0', rc == 0, "rc=%s" % rc)

# ── ③ 错误归因：--repo 无效目录不许归因 PATH ───────────────────────────────
print('— ③ --repo 指向无效目录 ⇒ 按真实原因报（不得归因 PATH）—')
bad = os.path.join(_REPO, "no-such-dir-xyz")
for script in (MR, GH):
    base = os.path.basename(script)
    rc, out = py([script] + SAME + ["--repo", bad])
    check('%s ⇒ 退 2' % base, rc == 2, "rc=%s" % rc)
    check('%s ⇒ 不再归因「未安装或不在 PATH」' % base,
          "未安装或不在 PATH" not in out, out.strip()[:100])
    check('%s ⇒ 指向真实原因「仓目录无效或无权限」' % base,
          "仓目录无效或无权限" in out, out.strip()[:100])

# ── ④ 反向证明：旧的全归因写法已不在源码里（防悄悄改回） ────────────────────
print('— ④ 反向证明：旧的全归因写法已不在源码 —')
for script in (MR, GH):
    src = open(os.path.join(_REPO, script), encoding="utf-8").read()
    check('%s 源码不含旧文案「未安装或不在 PATH？）：%%s — 」' % os.path.basename(script),
          "未安装或不在 PATH？）：%s — " not in src)

print('\n通过 %d / 失败 %d' % (pass_n, fail_n))
sys.exit(1 if fail_n else 0)
