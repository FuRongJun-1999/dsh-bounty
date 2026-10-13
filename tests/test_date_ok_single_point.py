# -*- coding: utf-8 -*-
"""test_date_ok_single_point.py · 两份同名同述的 **`date_ok`** 不得分叉

被修处（`scripts/evidence_check.py`）：
    全仓有两个同名同述的日期校验件：
      * `review_build.date_ok`  —— `DATE_RE.fullmatch(s)` ＋ `fromisoformat`（**形状＋日历**）
      * `evidence_check.date_ok` —— 旧实现只有 `fromisoformat` ＋ **`len(s) == 10`**

    `len(s) == 10` **不是形状判据**：**Python 3.11+ 的 `date.fromisoformat` 接受 ISO 周日期**，
    `"2026-W01-1"` 恰好 10 字符且可解析（⇒ `2025-12-29`）⇒ 旧实现判 **True**，
    而 `review_build` 判 **False**。

    判据文本自称「形状 ＋ 日历双判」—— 旧实现根本没有形状那一半。

本守卫四组：
  A 分叉面：两份实现在 15 例输入上**逐例一致**（本仓「口径单点」的机器判据）
  B 形状面：ISO 周日期等「可解析但非 `YYYY-MM-DD`」一律 False
  C 日历面：合法日期 True、不存在的日期（`2026-02-30`）False
  D **反向证明**：用**旧实现**（`fromisoformat` ＋ `len==10`）跑同一套 A ⇒ 必须**分叉**
"""
import sys
import os
import datetime

sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "evidence_check.py")
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import evidence_check as ec                                          # noqa: E402
import review_build as rb                                            # noqa: E402

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


#: 覆盖面：合法 / ISO 周日期 / 不存在的日期 / 形状不合 / 空白 / 非串
CASES = ["2026-10-13", "2026-12-31", "2026-01-01",
         "2026-W01-1", "2026-W41-7",                 # ISO 周日期（10 字符、可解析）
         "2026-02-30", "2026-13-01", "2026-00-10",   # 形状对但日历不存在
         "2026-1-1", "20261013", "2026/10/13", "99-99-99", "2026-01-1",
         "2026-10-13T00:00:00", "  2026-10-13  ", "2026-10-13\n",
         "", None, 20261013]


def _old_date_ok(text) -> bool:
    """★旧实现（逐字复刻 `evidence_check.py` 改动前的那 6 行）——仅供反向证明。"""
    s = str(text or "")
    try:
        datetime.date.fromisoformat(s)
    except ValueError:
        return False
    return len(s) == 10


print('— A 两份实现逐例一致（口径单点的机器判据）—')
_diverge = [(c, ec.date_ok(c), rb.date_ok(c)) for c in CASES if ec.date_ok(c) != rb.date_ok(c)]
check('A evidence_check.date_ok == review_build.date_ok（全部 %d 例）' % len(CASES),
      not _diverge, f'分叉：{_diverge}' if _diverge else '')

print('— B 形状面（可解析但不是 YYYY-MM-DD ⇒ 必须 False）—')
for _c in ("2026-W01-1", "2026-W41-7"):
    check(f'B 拒绝 ISO 周日期 {_c!r}', ec.date_ok(_c) is False and rb.date_ok(_c) is False,
          f'ec={ec.date_ok(_c)} rb={rb.date_ok(_c)}')
check('B 拒绝长度非 10 的串', ec.date_ok("2026-1-1") is False, '')
check('B 拒绝带时刻的串', ec.date_ok("2026-10-13T00:00:00") is False, '')
check('B 拒绝带首尾空白的串（`fullmatch` 语义）',
      ec.date_ok("  2026-10-13  ") is False and ec.date_ok("2026-10-13\n") is False, '')

print('— C 日历面 —')
check('C 合法日期 True', ec.date_ok("2026-10-13") is True and rb.date_ok("2026-10-13") is True, '')
check('C 不存在的日期 False（形状对但日历不过）',
      ec.date_ok("2026-02-30") is False and rb.date_ok("2026-02-30") is False, '')
check('C 非串/空值 False', ec.date_ok(None) is False and ec.date_ok("") is False, '')

print('— D 反向证明（旧实现必分叉）—')
_old_diverge = [(c, _old_date_ok(c), rb.date_ok(c)) for c in CASES if _old_date_ok(c) != rb.date_ok(c)]
check('D 旧实现在同一套输入上**与 review_build 分叉**（证明本守卫有判别力）',
      bool(_old_diverge), f'分叉 {len(_old_diverge)} 例：{_old_diverge[:3]}')
check('D 旧实现对 `2026-W01-1` 判 True（形状判据缺失的直接后果）',
      _old_date_ok("2026-W01-1") is True, '')

print('— E 静态面 —')
_SRC = open(_IMPL, encoding="utf-8").read()
check('E `evidence_check` 已有 DATE_RE（与 review_build 同款形状）',
      "DATE_RE = re.compile(r\"\\d{4}-\\d{2}-\\d{2}\")" in _SRC
      or 'DATE_RE = re.compile(r"\\d{4}-\\d{2}-\\d{2}")' in _SRC, '')
check('E `date_ok` 用 `DATE_RE.fullmatch`',
      "if not DATE_RE.fullmatch(s):" in _SRC, '')
check('E 不再用 `len(s) == 10` 当形状判据',
      "return len(s) == 10" not in _SRC, '')

print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
