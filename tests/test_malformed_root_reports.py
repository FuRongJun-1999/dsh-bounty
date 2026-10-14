# -*- coding: utf-8 -*-
"""畸形**根形状** ⇒ fail-closed 点名（不再裸 AttributeError／ValueError）

成员（三处都是「合法 JSON ⇒ 过得了 json.load，到 `.get()`／`int()` 才炸」）：
  ① `bounty_list.validate`：真源 `悬赏.json` 的**根**不是对象 ⇒ 裸 `AttributeError`
  ② `daily_table`：账本事件的 `delta` 非整数 ⇒ 裸 `ValueError: invalid literal for int()`
  ③ `evidence_check`：`review/data/plugins.json` 的**根**不是对象 ⇒ 裸 `AttributeError`

三个模块的 docstring 都承诺 fail-closed ＋ 可读报错，而它们的 CI 闸正是以这些判据面
为据。**元素**形状此前已有守卫（见 `test_*_element_shape.py`），本件补的是**根**那一面。
"""
import sys, os, json, io, tempfile, shutil, subprocess
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
    r = subprocess.run([sys.executable, "-X", "utf8"] + args, cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"), timeout=180)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ── ① bounty_list：真源**根**形状 ────────────────────────────────────────────
print('— ① bounty_list：真源根不是对象 —')


def bl_sandbox(root_val):
    d = tempfile.mkdtemp(prefix="malformed_root_bl_")
    os.makedirs(os.path.join(d, "scripts"), exist_ok=True)
    os.makedirs(os.path.join(d, "docs", "bounty"), exist_ok=True)
    shutil.copy(os.path.join(_REPO, "scripts", "bounty_list.py"),
                os.path.join(d, "scripts", "bounty_list.py"))
    io.open(os.path.join(d, "docs", "bounty", "悬赏.json"), "w",
            encoding="utf-8", newline="\n").write(json.dumps(root_val, ensure_ascii=False, indent=2))
    return d


for label, val in (("数组", []), ("null", None), ("数字", 5), ("字符串", "x")):
    d = bl_sandbox(val)
    rc, out = py([os.path.join(d, "scripts", "bounty_list.py"), "--check"])
    tail = out.strip().splitlines()[-1][:64] if out.strip() else ""
    check('① 根=%s ⇒ 不裸栈' % label, "Traceback" not in out, tail)
    check('① 根=%s ⇒ 退出码 2（fail-closed）' % label, rc == 2, 'rc=%s' % rc)
    check('① 根=%s ⇒ 点名「根不是对象」' % label, "根不是对象" in out, '')

d = bl_sandbox(json.load(io.open(os.path.join(_REPO, "docs", "bounty", "悬赏.json"), encoding="utf-8")))
rc, out = py([os.path.join(d, "scripts", "bounty_list.py"), "--stdout"])
check('① 合法真源仍 rc=0（零行为变更）', rc == 0, 'rc=%s' % (rc if rc else ''))


# ── ② daily_table：账本 delta 形状 ──────────────────────────────────────────
print('— ② daily_table：delta 非整数 —')


def dt_run(events):
    d = tempfile.mkdtemp(prefix="malformed_root_dt_")
    p = os.path.join(d, "ledger.json")
    io.open(p, "w", encoding="utf-8", newline="\n").write(
        json.dumps({"events": events}, ensure_ascii=False, indent=2))
    return py([os.path.join(_REPO, "scripts", "daily_table.py"), "--ledger", p, "--check"])


def ev(delta):
    return {"action": "settle", "id": "e1", "day": "2026-10-14", "holder": "a",
            "delta": delta, "reason": "r"}


rc, out = dt_run([ev("x")])
tail = out.strip().splitlines()[-1][:70] if out.strip() else ""
check('② delta="x" ⇒ 不裸栈', "Traceback" not in out, tail)
check('② delta="x" ⇒ rc=1', rc == 1, 'rc=%s' % rc)
check('② delta="x" ⇒ 报错点名 delta 与出处', "delta" in out and "ledger.json" in out, '')

for label, val in (("缺省", None), ("空串", ""), ("0", 0)):
    e = ev(val)
    if val is None:
        e.pop("delta")
    rc, out = dt_run([e])
    check('② delta=%s ⇒ 仍按 0 计（旧口径逐位不变）' % label, rc == 0, 'rc=%s' % rc)
rc, out = dt_run([ev(3)])
check('② delta=3 ⇒ rc=0', rc == 0, 'rc=%s' % rc)


# ── ③ evidence_check：测评数据根形状 ────────────────────────────────────────
print('— ③ evidence_check：测评数据根不是对象 —')
sys.path.insert(0, os.path.join(_REPO, "scripts"))
import evidence_check as ec


def ev_sandbox(plugins_val):
    d = tempfile.mkdtemp(prefix="malformed_root_ev_")
    os.makedirs(os.path.join(d, "review", "data"), exist_ok=True)
    os.makedirs(os.path.join(d, "review", "evidence"), exist_ok=True)
    io.open(os.path.join(d, "review", "data", "plugins.json"), "w",
            encoding="utf-8", newline="\n").write(json.dumps(plugins_val, ensure_ascii=False, indent=2))
    io.open(os.path.join(d, "review", "evidence", "manifest.json"), "w", encoding="utf-8", newline="\n").write(
        json.dumps({"documents": [{"file": "x.txt", "kind": "README", "source_url": "u",
                                   "sha256": "0" * 64, "bytes": 0, "fetched_at": "2026-01-01"}]},
                   ensure_ascii=False, indent=2))
    return d


for label, val in (("字符串", "x"), ("数组", []), ("null", None)):
    d = ev_sandbox(val)
    try:
        ec.audit(root=d, want_repro=False)
        check('③ 根=%s ⇒ 抛 ValueError' % label, False, '未抛（静默通过＝判据失明）')
    except ValueError as exc:
        check('③ 根=%s ⇒ 抛 ValueError（不裸栈）' % label, "records" in str(exc), str(exc)[:72])
    except Exception as exc:                                   # noqa: BLE001
        check('③ 根=%s ⇒ 抛 ValueError（不裸栈）' % label, False,
              '%s: %s' % (type(exc).__name__, exc))
# 报错须点名**实读**路径（--root 指到别处时不得再点名模块自带的 PLUGINS 常量）
d = ev_sandbox("x")
try:
    ec.audit(root=d, want_repro=False)
except ValueError as exc:
    check('③ 报错点名实读路径（--root 下的 plugins.json）', d.replace('\\', '/') in str(exc).replace('\\', '/'),
          str(exc)[-56:])


# ── 反向证明：旧写法已不在源码里 ───────────────────────────────────────────
print('— 反向证明 —')
SRC_BL = io.open(os.path.join(_REPO, "scripts", "bounty_list.py"), encoding="utf-8").read()
SRC_DT = io.open(os.path.join(_REPO, "scripts", "daily_table.py"), encoding="utf-8").read()
SRC_EV = io.open(os.path.join(_REPO, "scripts", "evidence_check.py"), encoding="utf-8").read()
check('① 根判据锚点在位', 'if not isinstance(doc, dict):' in SRC_BL, '')
check('① 旧写法不再出现（errs 后直接 .get）',
      '    errs = []\n    if not isinstance(doc.get("items")' not in SRC_BL, '')
check('② delta 判据锚点在位', 'int(_delta)' in SRC_DT, '')
check('③ 根判据锚点在位', 'data.get("records") if isinstance(data, dict) else None' in SRC_EV, '')
check('③ 旧写法不再出现（无保护的 data.get("records")）',
      '    recs = data.get("records")\n' not in SRC_EV, '')

print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
