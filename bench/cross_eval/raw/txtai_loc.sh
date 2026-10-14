#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
{
echo "### metrics.loc（非空且不以 # 开头的行数）"
/usr/bin/python3 -X utf8 -c "
import sys; sys.path.insert(0,'bench/cross_eval/harness')
from metrics import loc
for p in ['bench/cross_eval/systems/txtai_impl.py','bench/cross_eval/harness/baseline.py']:
    print('loc(%-45s) = %d' % (p, loc(p)))
"
echo "### 编排单元数：txtai_impl.py 里 Task( 出现次数"
grep -c 'Task(' bench/cross_eval/systems/txtai_impl.py
echo "### txtai_impl.py 里五个步骤名的 Task 定义行"
grep -n 'name=' bench/cross_eval/systems/txtai_impl.py
echo "### baseline.py 里模式函数定义"
grep -n '^def ' bench/cross_eval/harness/baseline.py
} 2>&1 | tee bench/cross_eval/raw/txtai_loc.txt
