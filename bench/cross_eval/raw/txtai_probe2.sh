#!/usr/bin/env bash
set -u
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
cd /tmp
echo "=== cold import timing ==="
/usr/bin/python3 -X utf8 -c "
import time
t0=time.perf_counter()
import txtai
t1=time.perf_counter()
from txtai import Workflow
t2=time.perf_counter()
from txtai.workflow import Task
t3=time.perf_counter()
print('import txtai ms', round((t1-t0)*1000,3))
print('from txtai import Workflow ms', round((t2-t1)*1000,3))
print('from txtai.workflow import Task ms', round((t3-t2)*1000,3))
print('txtai version', txtai.__version__)
print('Workflow has save:', hasattr(Workflow,'save'), 'load:', hasattr(Workflow,'load'))
print('Workflow attrs:', [a for a in dir(Workflow) if not a.startswith('_')])
print('Task attrs:', [a for a in dir(Task) if not a.startswith('_')])
"
echo "=== try Task(retries=3) ==="
/usr/bin/python3 -X utf8 -c "
from txtai.workflow import Task
try:
    t = Task(action=lambda x: x, retries=3)
    print('accepted retries ->', t)
except Exception as e:
    print('Task(retries=3) ->', type(e).__name__ + ': ' + str(e))
"
echo "=== try Workflow(tasks=[], checkpoint=True) ==="
/usr/bin/python3 -X utf8 -c "
from txtai import Workflow
try:
    w = Workflow(tasks=[], checkpoint=True)
    print('accepted checkpoint ->', w)
except Exception as e:
    print('Workflow(checkpoint=True) ->', type(e).__name__ + ': ' + str(e))
"
echo "=== thread fanout probe: 4 actions, concurrency=thread, workers=4 ==="
/usr/bin/python3 -X utf8 -c "
import threading, time
from txtai import Workflow
from txtai.workflow import Task
def mk(i):
    def f(batch):
        tid = threading.get_ident()
        time.sleep(0.30)
        return [[('action', i, 'thread', tid, 'n', len(batch))]]
    return f
t = Task(action=[mk(i) for i in range(4)], concurrency='thread', unpack=False, merge='vstack')
w = Workflow(tasks=[t], workers=4)
t0=time.perf_counter()
out = list(w([['q%02d'%i for i in range(40)]]))
el=time.perf_counter()-t0
print('elapsed_ms', round(el*1000,1))
for o in out: print('OUT', o)
"
echo "=== single action, concurrency=thread, workers=4 (control) ==="
/usr/bin/python3 -X utf8 -c "
import threading, time
from txtai import Workflow
from txtai.workflow import Task
def f(batch):
    tid = threading.get_ident()
    time.sleep(0.30)
    return [('one','thread',tid)]
t = Task(action=[f], concurrency='thread', unpack=False)
w = Workflow(tasks=[t], workers=4)
t0=time.perf_counter()
out = list(w([['q%02d'%i for i in range(40)]]))
print('elapsed_ms', round((time.perf_counter()-t0)*1000,1))
print('OUT', out)
"
