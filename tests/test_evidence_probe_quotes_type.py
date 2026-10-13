# -*- coding: utf-8 -*-
"""test_evidence_probe_quotes_type.py · 探针必须**判 `quotes` 的容器类型**

被修处（`scripts/evidence_probe.py`）：
    旧实现 `for q in (e.get("quotes") or []):` —— **三件工具里唯一不判类型的**。
    （`evidence_check.py` 判 `isinstance(quotes, list)`；`review_build.py` 判
    「须为非空字符串数组」。）

    后果：
      * `quotes = "遗忘"` ⇒ 迭代出 `'遗'`、`'忘'` **单字** ⇒ 单字在十万字节文档里几乎必然
        命中 ⇒ 探针报「[OK] … 本记录的证据链在本机逐字节成立」，而**同一份数据**
        `evidence_check` 报 NG ⇒ **两件结论相反**（恰好绕过 `MIN_QUOTE_LEN` 的存在理由）；
      * `quotes = {"引文": 1}` ⇒ 迭代出**字典的键**；
      * `quotes = 5` / `True` ⇒ `TypeError` 崩栈（契约要求退 2）。

本守卫在**沙箱副本**里跑子进程（探针的 `ROOT` 由**本文件位置**决定，故必须整仓复制）。

四组：
  A 坏容器（str / dict / int / bool）⇒ 探针**退 1 且点名 `quotes 须为`**，不崩、不假 OK
  B 与校验件**结论一致**（同一份坏数据两边都判非 0）
  C 合法数据**零行为变更**（探针 stdout 与未改动实现逐字节相同）
  D **反向证明**：旧实现（无限定）对 `quotes="遗忘"` 报 **OK / 退 0**（假通过）
"""
import sys
import os
import json
import shutil
import subprocess
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
PY = sys.executable

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


def _sandbox():
    d = tempfile.mkdtemp(prefix="probe_quotes_")
    shutil.copytree(_REPO, d, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    return d


def _set_quotes(d, val):
    p = os.path.join(d, "review", "data", "plugins.json")
    doc = json.load(open(p, encoding="utf-8"))
    doc["records"][0]["evidence"][0]["quotes"] = val
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    return doc


def _probe(d, pid="record.dsh-memory"):
    return subprocess.run([PY, "-X", "utf8", "scripts/evidence_probe.py", pid],
                          capture_output=True, text=True, encoding="utf-8", cwd=d)


def _checker(d):
    return subprocess.run([PY, "-X", "utf8", "scripts/evidence_check.py",
                           "--root", d, "--no-repro"],
                          capture_output=True, text=True, encoding="utf-8", cwd=d)


# 基线：合法数据的探针输出（用于 C 组的零行为变更比对）
_base = _sandbox()
_before = _probe(_base, "--all")

print('— A 坏容器一律点名 NG，不崩、不假 OK —')
for _label, _val in (('字符串 "遗忘"', "遗忘"), ('字典 {"引文": 1}', {"引文": 1}),
                     ('整数 5', 5), ('布尔 True', True)):
    _d = _sandbox()
    _set_quotes(_d, _val)
    _r = _probe(_d)
    _bad_line = [l for l in _r.stdout.splitlines() if "quotes 须为" in l]
    check(f'A quotes={_label} ⇒ 退 1', _r.returncode == 1, f'rc={_r.returncode}')
    check(f'A quotes={_label} ⇒ 点名「quotes 须为」', bool(_bad_line),
          _bad_line[0][:70] if _bad_line else '(无该行)')
    check(f'A quotes={_label} ⇒ 不出现「证据链在本机逐字节成立」',
          "证据链在本机逐字节成立" not in _r.stdout, '')
    check(f'A quotes={_label} ⇒ 不崩栈', "Traceback" not in _r.stderr, _r.stderr.strip()[-70:])
    shutil.rmtree(_d, ignore_errors=True)

print('— B 与校验件结论一致（同一份坏数据两边都非 0）—')
for _label, _val in (('字符串 "遗忘"', "遗忘"), ('字典', {"引文": 1}), ('整数 5', 5)):
    _d = _sandbox()
    _set_quotes(_d, _val)
    _p, _c = _probe(_d), _checker(_d)
    check(f'B quotes={_label} ⇒ 探针与校验件都判非 0（结论不再相反）',
          _p.returncode != 0 and _c.returncode != 0,
          f'探针 rc={_p.returncode} ｜ 校验件 rc={_c.returncode}')
    shutil.rmtree(_d, ignore_errors=True)

print('— C 合法数据零行为变更 —')
_after = _probe(_base, "--all")
check('C 现有合法数据的探针 stdout 与改动前**逐字节相同**',
      _before.stdout == _after.stdout,
      'len %d vs %d' % (len(_before.stdout), len(_after.stdout)))
check('C 现有合法数据探针仍退 0', _after.returncode == 0, f'rc={_after.returncode}')

print('— D 反向证明（旧实现假通过）—')
_SRC = open(os.path.join(_REPO, "scripts", "evidence_probe.py"), encoding="utf-8").read()
_OLD_BLOCK = ("        _quotes = e.get(\"quotes\")\n"
              "        if _quotes is None:\n"
              "            continue\n"
              "        if not isinstance(_quotes, list):\n"
              "            n_ng += 1\n"
              "            lines.append(\"[NG] evidence[%d] doc=%s quotes 须为引文字符串数组（实为 %s）\"\n"
              "                         % (i, doc, type(_quotes).__name__))\n"
              "            continue\n"
              "        for q in _quotes:")
check('D0 还原旧实现的锚点命中', _SRC.count(_OLD_BLOCK) == 1,
      f'命中 {_SRC.count(_OLD_BLOCK)} 次')
if _SRC.count(_OLD_BLOCK) == 1:
    _OLD = _SRC.replace(_OLD_BLOCK, "        for q in (e.get(\"quotes\") or []):", 1)
    _d = _sandbox()
    open(os.path.join(_d, "scripts", "evidence_probe.py"), "w",
         encoding="utf-8", newline="\n").write(_OLD)
    _set_quotes(_d, "遗忘")
    _r = _probe(_d)
    check('D 旧实现对 quotes="遗忘" **退 0**（假通过）', _r.returncode == 0, f'rc={_r.returncode}')
    check('D 旧实现报「证据链在本机逐字节成立」（结论与校验件相反）',
          "证据链在本机逐字节成立" in _r.stdout, '')
    shutil.rmtree(_d, ignore_errors=True)

shutil.rmtree(_base, ignore_errors=True)
print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
