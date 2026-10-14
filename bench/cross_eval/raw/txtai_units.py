import sys, json
sys.path.insert(0, "bench/cross_eval/harness")
sys.path.insert(0, "bench/cross_eval/systems")

import txtai.workflow as W
orig = W.Workflow
built = []

class Rec(orig):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        built.append({"n_tasks": len(self.tasks), "workers": self.workers, "batch": self.batch})

W.Workflow = Rec

import txtai_impl
print("NAME =", txtai_impl.NAME)
print("CAPS =", json.dumps(txtai_impl.CAPS, ensure_ascii=False))

cfg = {"corpus": "bench/cross_eval/data/corpus.jsonl",
       "queries": "bench/cross_eval/data/queries.jsonl",
       "out": "/tmp/txtai_units_out.jsonl",
       "workers": 4, "k": 5}

for mode in ["normal", "resume", "retry", "sequential", "parallel"]:
    built.clear()
    r = txtai_impl.run(mode, cfg)
    info = built[0] if built else None
    print("mode=%-11s ok=%s Workflow实例数=%d 每个实例Task数=%s"
          % (mode, r.get("ok"), len(built), [b["n_tasks"] for b in built]))
    if info:
        print("            workers=%s batch=%s" % (info["workers"], info["batch"]))
