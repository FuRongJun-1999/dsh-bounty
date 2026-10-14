#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
# txtai 能力探针：为报告 §4 M4/M5/M7 提供依据（原始输出落 raw/txtai_capability_probe.txt）
set -u
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
T=/home/ubuntu/dm/pylibs/txtai/txtai
cd "$ROOT"

echo "### A. 源码检索：检查点 / 恢复 / 重试（txtai 9.14.0, $T）"
echo "--- grep -rn -iE 'checkpoint|resume|restart' $T/workflow/ ---"
grep -rn -iE 'checkpoint|resume|restart' "$T/workflow/" || echo "(0 命中)"
echo "--- grep -rn -iE 'retry|retries|backoff' $T/workflow/ ---"
grep -rn -iE 'retry|retries|backoff' "$T/workflow/" || echo "(0 命中)"
echo "--- grep -rn -iE 'def save|def load|pickle|json.dump' $T/workflow/base.py ---"
grep -rn -iE 'def save|def load|pickle|json.dump' "$T/workflow/base.py" || echo "(0 命中)"
echo "--- Workflow 公开 API ---"
/usr/bin/python3 -X utf8 -c "
from txtai.workflow import Workflow
print('Workflow public attrs:', [a for a in dir(Workflow) if not a.startswith('_')])
print('hasattr save/load/checkpoint/resume:',
      hasattr(Workflow,'save'), hasattr(Workflow,'load'), hasattr(Workflow,'checkpoint'), hasattr(Workflow,'resume'))
"

echo
echo "### B. 尝试过的做法 + 原始报错（真实调用，真实异常，不伪造）"
/usr/bin/python3 -X utf8 -c "
from txtai.workflow import Task
from txtai.workflow import Workflow
cases = [
    ('Task(retries=3)', lambda: Task(action=lambda x: x, retries=3)),
    ('Task(retry=3)', lambda: Task(action=lambda x: x, retry=3)),
    ('Task(on_error=...)', lambda: Task(action=lambda x: x, on_error=lambda e: None)),
    ('Workflow(checkpoint=True)', lambda: Workflow(tasks=[], checkpoint=True)),
    ('Workflow(resume=True)', lambda: Workflow(tasks=[], resume=True)),
    ('Workflow(checkpoint_dir=...)', lambda: Workflow(tasks=[], workers=4, checkpoint_dir='/tmp/ckpt')),
]
for label, fn in cases:
    try:
        fn()
        print(label, '-> ACCEPTED (unexpected)')
    except Exception as e:
        print(label, '->', type(e).__name__ + ': ' + str(e))
"

echo
echo "### C. M7 探针：某个 Task 抛异常时，引擎自己的错误文本/栈是否点名步骤"
/usr/bin/python3 -X utf8 bench/cross_eval/raw/txtai_probe_m7.py 2>&1

echo
echo "### D. 并发原语作用域探针：单 action 任务是否并发（对照 4 action）"
/usr/bin/python3 -X utf8 bench/cross_eval/raw/txtai_probe_fanout.py 2>&1
