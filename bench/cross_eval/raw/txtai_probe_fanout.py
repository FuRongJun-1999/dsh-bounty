import threading, time
from txtai.workflow import Task, Workflow

SLEEP = 0.30
TIDS = []
LOCK = threading.Lock()

def sleeper(tag, batch):
    with LOCK:
        TIDS.append((tag, threading.get_ident()))
    time.sleep(SLEEP)
    return [{'tag': tag}]

def mk_actions(n):
    acts = []
    for i in range(n):
        def mk(i):
            return lambda b: sleeper('a%d' % i, b)
        acts.append(mk(i))
    return acts

def timed(label, task, workers):
    global TIDS
    TIDS = []
    wf = Workflow(tasks=[task], workers=workers)
    s = time.perf_counter()
    list(wf([(0, 'x', 'run')]))
    el = (time.perf_counter() - s) * 1000
    threads = sorted(set(t for _, t in TIDS))
    print('%-40s elapsed_ms=%8.1f  invocations=%d  distinct_threads=%d'
          % (label, el, len(TIDS), len(threads)))

print('每个 action sleep %.2fs；期望：4 action 串行 ~1200ms，4 action 并发 ~300ms' % SLEEP)
timed('1 action  concurrency=None', Task(action=mk_actions(1), unpack=True), None)
timed('4 action  concurrency=None (串行)', Task(action=mk_actions(4), unpack=True), None)
timed('4 action  concurrency=thread w=4', Task(action=mk_actions(4), concurrency='thread', unpack=True), 4)
try:
    timed('4 action  concurrency=process w=4', Task(action=mk_actions(4), concurrency='process', unpack=True), 4)
except Exception as e:
    print('%-40s -> %s: %s' % ('4 action  concurrency=process w=4', type(e).__name__, str(e).splitlines()[0]))
