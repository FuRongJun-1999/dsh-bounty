#!/usr/bin/env bash
set -u
export PYTHONPATH=/home/ubuntu/dm/pylibs/base:/home/ubuntu/dm/pylibs/txtai
echo "=== txtai version file ==="
cat /home/ubuntu/dm/pylibs/txtai/txtai/version.py
echo "=== version() call ==="
/usr/bin/python3 -X utf8 -c "
from txtai.version import __version__
print('txtai.__version__ =', __version__)
"
echo "=== import breakdown (fresh processes) ==="
/usr/bin/python3 -X utf8 -c "
import time
t0=time.perf_counter(); import torch; t1=time.perf_counter()
print('import torch ms', round((t1-t0)*1000,3), 'torch', torch.__version__)
"
/usr/bin/python3 -X utf8 -c "
import time
t0=time.perf_counter(); from txtai.workflow import Workflow; t1=time.perf_counter()
print('from txtai.workflow import Workflow ms', round((t1-t0)*1000,3))
"
/usr/bin/python3 -X utf8 -c "
import time
t0=time.perf_counter(); import txtai; t1=time.perf_counter()
print('import txtai ms', round((t1-t0)*1000,3))
"
echo "=== du -sh ==="
du -sh /home/ubuntu/dm/pylibs/txtai
du -sh /home/ubuntu/dm/pylibs/base
du -sh /home/ubuntu/dm/pylibs/txtai/torch
du -sh /home/ubuntu/dm/pylibs/txtai/nvidia 2>/dev/null || echo 'no nvidia dir'
echo "=== nproc / mem ==="
nproc
free -m | head -2
