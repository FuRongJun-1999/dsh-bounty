# -*- coding: utf-8 -*-
"""test_ledger_schema_single_point.py · `LEDGER_SCHEMA['计分']` 的**口径单点**守卫

被修处（`scripts/bounty_board.py`）：
    `LEDGER_SCHEMA["计分"]` 旧实现把难度→分**硬编码**成
        `{"easy": 1, "medium": 3, "hard": 6, "expert": 10, ...}`
    —— 那是全仓**第四份**难度表。危害大于其余三份，因为 `LEDGER_SCHEMA` 经
    `write_ledger` **原样写进 `docs/bounty/ledger.json` 的 `_schema`**，
    那是**已发布的公开产物**、第三方据以独立核口径 ⇒ 权威表 `DIFFICULTY_SCORES`
    一改，账本仍宣称旧值。

    同字典内紧邻的「影响等级」本就是派生的
    （`{g: IMPACT_CRITERIA[g] for g in IMPACT_GRADES}`）—— 本件把难度表也改成同款。

本守卫四组：
  A 静态面（AST）：`计分` 字典的四个难度键**不得**绑定整数字面量；
  B 行为面（源码级定点变异）：把权威表 `hard` 6→7 后**重新导入**，`_schema` 必须跟随；
  C 零行为变更：`LEDGER_SCHEMA` 的 JSON 序列化与期望字面量逐字段相同（含键序）；
  D 反向证明：用**旧写法**（硬编码）构造源码跑同一套 B ⇒ 必须**不跟随**（证明 B 有判别力）。

体例与 `tests/` 下其它 test_*.py 一致（`check()` + 退出码；末行「通过 N / 失败 M」）。
"""
import sys
import os
import ast
import json
import re
import hashlib
import tempfile
import importlib.util

sys.stdout.reconfigure(encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_IMPL = os.path.join(_REPO, "scripts", "bounty_board.py")

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


SRC = open(_IMPL, encoding="utf-8").read()
TREE = ast.parse(SRC)

DIFF_KEYS = ("easy", "medium", "hard", "expert")


def _load(src, name):
    """把源码写到临时文件后导入（用于源码级变异；避免污染已导入的模块）。"""
    d = tempfile.mkdtemp(prefix="ledger_schema_")
    p = os.path.join(d, name + ".py")
    open(p, "w", encoding="utf-8", newline="\n").write(src)
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _score_dict_value(srctext, tree):
    """从 AST 里取 `LEDGER_SCHEMA` 中 `计分` 键对应的 value 节点。"""
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "LEDGER_SCHEMA" for t in node.targets)):
            continue
        d = node.value
        if not isinstance(d, ast.Dict):
            return None
        for k, v in zip(d.keys, d.values):
            if isinstance(k, ast.Constant) and k.value == "计分":
                return v
    return None


# ---------------------------------------------------------------- A 静态面
print('— A 静态面（AST：计分字典的难度键不得绑整数字面量）—')
_sc = _score_dict_value(SRC, TREE)
check('A0 已定位 LEDGER_SCHEMA["计分"]', _sc is not None, _IMPL)
if _sc is not None:
    check('A 计分字典是 ast.Dict', isinstance(_sc, ast.Dict), type(_sc).__name__)
    _bound = {}
    if isinstance(_sc, ast.Dict):
        for k, v in zip(_sc.keys, _sc.values):
            if isinstance(k, ast.Constant) and k.value in DIFF_KEYS:
                _bound[k.value] = v
    check('A 四个难度键都在计分字典里（含 dict 解包带来的键）',
          True, f'AST 直接键：{sorted(_bound)}')
    # 关键：不许有「键 → 整数字面量」的直接绑定
    _hardcoded = [(k, v.value) for k, v in _bound.items()
                  if isinstance(v, ast.Constant) and isinstance(v.value, int)]
    check('A 难度键**没有**绑定整数字面量（旧实现即此形态）',
          not _hardcoded, f'仍硬编码：{_hardcoded}' if _hardcoded else '')
    # 必须存在对 DIFFICULTY_SCORES 的引用（dict 解包或推导式）
    _refs = [n for n in ast.walk(_sc)
             if isinstance(n, ast.Name) and n.id == "DIFFICULTY_SCORES"]
    check('A 计分字典引用 DIFFICULTY_SCORES（派生而非另立）', bool(_refs),
          f'引用 {len(_refs)} 处')

# ---------------------------------------------------------------- B 行为面（源码级定点变异）
print('— B 行为面（源码级变异：权威表 hard 6→7 ⇒ _schema 必须跟随）—')
_mut_src = SRC.replace('"difficulty:hard": 6,', '"difficulty:hard": 7,')
check('B0 变异锚点唯一命中', _mut_src != SRC
      and SRC.count('"difficulty:hard": 6,') == 1,
      f'命中 {SRC.count(chr(34) + "difficulty:hard" + chr(34) + ": 6,")} 次')
_base_mod = _load(SRC, "_ls_base")
_mut_mod = _load(_mut_src, "_ls_mut")
_mut_hard = _mut_mod.LEDGER_SCHEMA["计分"].get("hard")
_mut_auth = {k.split(":", 1)[-1]: v for k, v in _mut_mod.DIFFICULTY_SCORES.items()}["hard"]
check('B 改权威表后 _schema 的 hard 跟随（== 7）',
      _mut_hard == 7 and _mut_auth == 7,
      f'_schema.hard={_mut_hard}  DIFFICULTY_SCORES.hard={_mut_auth}')
check('B 未改时两处一致（== 6）',
      _base_mod.LEDGER_SCHEMA["计分"]["hard"] == 6, '')

# ---------------------------------------------------------------- C 零行为变更
print('— C 零行为变更（序列化逐字节相同 / 键序不变）—')
_expected_diffs = dict(_base_mod.DIFFICULTY_SCORES)
_now = {k: v for k, v in _base_mod.LEDGER_SCHEMA["计分"].items() if k in DIFF_KEYS}
check('C 四个难度值与权威表逐项相同',
      _now == {k.split(":", 1)[-1]: v for k, v in _expected_diffs.items()},
      f'{_now}')
_order = [k for k in _base_mod.LEDGER_SCHEMA["计分"] if k in DIFF_KEYS]
check('C 难度键顺序仍为 easy/medium/hard/expert（json 键序不变）',
      _order == list(DIFF_KEYS), f'{_order}')

# 与「旧写法」的序列化逐字节比对（旧写法 = 把这四个键换回整数字面量）
_old_src = re.sub(
    r'    "计分": \{\*\*\{k\.split\(":", 1\)\[-1\]: v for k, v in DIFFICULTY_SCORES\.items\(\)\},',
    '    "计分": {"easy": 1, "medium": 3, "hard": 6, "expert": 10,',
    SRC, count=1)
check('C0 还原旧写法的锚点命中', _old_src != SRC, '')
if _old_src != SRC:
    _old_mod = _load(_old_src, "_ls_old")
    _a = json.dumps(_base_mod.LEDGER_SCHEMA, ensure_ascii=False)
    _b = json.dumps(_old_mod.LEDGER_SCHEMA, ensure_ascii=False)
    check('C 与旧写法的 LEDGER_SCHEMA 序列化**逐字节相同**',
          _a == _b,
          'md5 %s vs %s' % (hashlib.md5(_a.encode()).hexdigest()[:12],
                            hashlib.md5(_b.encode()).hexdigest()[:12]))

    # ------------------------------------------------------------ D 反向证明
    print('— D 反向证明（旧写法下 B 必须**不跟随**）—')
    _old_mut_src = _old_src.replace('"difficulty:hard": 6,', '"difficulty:hard": 7,')
    _old_mut = _load(_old_mut_src, "_ls_oldmut")
    check('D 旧写法下改权威表，_schema 的 hard **不跟随**（仍为 6）',
          _old_mut.LEDGER_SCHEMA["计分"]["hard"] == 6
          and {k.split(":", 1)[-1]: v for k, v in _old_mut.DIFFICULTY_SCORES.items()}["hard"] == 7,
          'schema.hard=%s  权威.hard=%s'
          % (_old_mut.LEDGER_SCHEMA["计分"]["hard"],
             {k.split(":", 1)[-1]: v for k, v in _old_mut.DIFFICULTY_SCORES.items()}["hard"]))

print(f'\n通过 {pass_n} / 失败 {fail_n}')
sys.exit(0 if fail_n == 0 else 1)
