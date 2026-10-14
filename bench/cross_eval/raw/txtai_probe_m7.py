import traceback
from txtai.workflow import Task, Workflow

def ok(batch):
    return batch

def boom(batch):
    raise RuntimeError('boom')

tasks = [Task(action=[ok], unpack=True), Task(action=[boom], unpack=True), Task(action=[ok], unpack=True)]
wf = Workflow(tasks=tasks)
try:
    list(wf([(0, 'x', 'run')]))
except Exception:
    tb = traceback.format_exc()
    print('--- engine traceback (task #2 of 3 raises RuntimeError("boom")) ---')
    print(tb)
    print('--- engine frames mention task name/index? ---')
    print('contains Task-name marker :', ('Task #' in tb))
    print('last line                 :', tb.strip().splitlines()[-1])
