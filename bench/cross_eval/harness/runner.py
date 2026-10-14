"""统一跑法：加载一个实现模块，按模式跑，落原始文本 + 机器可读摘要。

用法：
  PYTHONPATH=<base target>:harness python3 -X utf8 harness/runner.py \
      --impl systems/langgraph_impl.py --name langgraph --modes normal,resume,retry,parallel,sequential

所有读数以本脚本打印的原文为准；报告里只能引用 raw/<name>_<mode>.txt 的内容。
"""
import argparse
import importlib.util
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import metrics  # noqa: E402
import workload  # noqa: E402

GOLDEN = os.path.join(HERE, os.pardir, "data", "out_baseline.jsonl")


def load_impl(path):
    spec = importlib.util.spec_from_file_location("impl_" + os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cfg_for(mode, args, out_path):
    cfg = {"corpus": args.corpus, "queries": args.queries, "out": out_path,
           "workers": args.workers, "k": workload.K_TOP}
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--modes", default="normal,resume,retry,parallel,sequential")
    ap.add_argument("--corpus", default=os.path.join(HERE, os.pardir, "data", "corpus.jsonl"))
    ap.add_argument("--queries", default=os.path.join(HERE, os.pardir, "data", "queries.jsonl"))
    ap.add_argument("--rawdir", default=os.path.join(HERE, os.pardir, "raw"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--repeats", type=int, default=7)
    ap.add_argument("--skip-timing", action="store_true")
    args = ap.parse_args()

    mod = load_impl(os.path.abspath(args.impl))
    os.makedirs(args.rawdir, exist_ok=True)
    summary = {"name": args.name, "impl": os.path.relpath(os.path.abspath(args.impl)),
               "caps": getattr(mod, "CAPS", {}), "modes": {}}
    print("IMPL %s NAME %s" % (os.path.relpath(os.path.abspath(args.impl)), args.name))
    print("CAPS %s" % json.dumps(getattr(mod, "CAPS", {}), ensure_ascii=False, sort_keys=True))

    for mode in [m for m in args.modes.split(",") if m]:
        out_path = os.path.join(args.rawdir, "%s_out_%s.jsonl" % (args.name, mode))
        lines = []
        rec = {"mode": mode}
        try:
            r = mod.run(mode, cfg_for(mode, args, out_path))
            rec["ok"] = bool(r.get("ok"))
            for key in ("trace", "attempts", "first_error", "error_text",
                        "steps_reexecuted_after_failure", "note"):
                if key in r:
                    rec[key] = r[key]
            if os.path.exists(out_path):
                rec["sha256"] = metrics.sha256_file(out_path)
                rec["sha256_golden"] = metrics.sha256_file(GOLDEN)
                rec["matches_golden"] = rec["sha256"] == rec["sha256_golden"]
                rec["lines"] = sum(1 for _ in open(out_path, "r", encoding="utf-8"))
            lines.append("RUN mode=%s ok=%s" % (mode, rec["ok"]))
            if "matches_golden" in rec:
                lines.append("SHA %s golden=%s match=%s lines=%s"
                             % (rec["sha256"], rec["sha256_golden"], rec["matches_golden"], rec["lines"]))
            if "trace" in rec:
                lines.append("TRACE %s" % json.dumps(rec["trace"], ensure_ascii=False))
            if "attempts" in rec:
                lines.append("ATTEMPTS %s" % rec["attempts"])
            if "first_error" in rec:
                lines.append("FIRST_ERROR %s" % rec["first_error"])
            if "steps_reexecuted_after_failure" in rec:
                lines.append("REEXECUTED %s" % json.dumps(rec["steps_reexecuted_after_failure"], ensure_ascii=False))
            if "error_text" in rec:
                lines.append("ERROR_TEXT %s" % str(rec["error_text"]).replace("\n", " | ")[:400])
        except Exception as e:
            rec["ok"] = False
            rec["exception"] = "%s: %s" % (type(e).__name__, e)
            lines.append("RUN mode=%s EXCEPTION %s" % (mode, rec["exception"]))
            lines.append("TRACEBACK " + traceback.format_exc().replace("\n", " | ")[:800])
        summary["modes"][mode] = rec
        txt = "\n".join(lines) + "\n"
        with open(os.path.join(args.rawdir, "%s_%s.txt" % (args.name, mode)), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(txt)
        print(txt.rstrip())

    if not args.skip_timing:
        for mode in ("normal", "sequential", "parallel"):
            try:
                t = metrics.timeit(lambda m=mode: mod.run(m, cfg_for(mode, args,
                                 os.path.join(args.rawdir, "%s_timing.jsonl" % args.name))),
                                   repeats=args.repeats, warmup=1)
                summary["timing_%s" % mode] = t
                print("TIMING %s %s" % (mode, json.dumps(t, sort_keys=True)))
            except Exception as e:
                summary["timing_%s" % mode] = {"error": "%s: %s" % (type(e).__name__, e)}
                print("TIMING %s ERROR %s" % (mode, e))

    metrics.jdump(summary, os.path.join(args.rawdir, "%s_summary.json" % args.name))
    print("SUMMARY_WRITTEN raw/%s_summary.json" % args.name)


if __name__ == "__main__":
    main()
