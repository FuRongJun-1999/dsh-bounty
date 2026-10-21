"""统一跑法：加载一个实现模块，按模式跑，落原始文本 + 机器可读摘要。

用法：
  PYTHONPATH=<base target>:harness python3 -X utf8 harness/runner.py \
      --impl systems/langgraph_impl.py --name langgraph --modes normal,resume,retry,parallel,sequential

所有读数以本脚本打印的原文为准；报告里只能引用 raw/<name>_<mode>.txt 的内容。

退出码：0 = 所有模式 ok 且计时面无 error；1 = 有模式失败（异常 / ok 非真）或有计时 error。
（旧版 main() 末尾没有 sys.exit ⇒ 五个模式全异常仍 EXIT=0，`| tee` 的调用方读不到成败。）
证据：实现返回的键**全量**并入 summary 与 REC/EVIDENCE 行（旧版只搬 6 个白名单键，
其余静默丢弃——实测 steps_reused_from_checkpoint / counts_* / workers / results 全丢）；
不可 JSON 序列化的键名记入 dropped_keys，不静默消失。
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


def carry_evidence(rec, r):
    """把实现返回的每个证据键**全量**搬进 rec（白名单会静默丢键）。

    不可 JSON 序列化的键不落盘，但**显式记名**在 dropped_keys 里，不静默消失。
    """
    carried, dropped = [], []
    for key in sorted(r):
        if key == "mode":
            continue
        val = r[key]
        try:
            json.dumps(val, ensure_ascii=False)
        except (TypeError, ValueError):
            dropped.append(key)
            continue
        rec[key] = val
        carried.append(key)
    rec["carried_keys"] = carried
    rec["dropped_keys"] = dropped
    return carried, dropped


def conclusion_of(rec):
    """可判读的失败结论字段：异常或 ok 非真 ⇒ FAIL，否则 OK。"""
    if rec.get("exception"):
        return "FAIL"
    return "OK" if rec.get("ok") is True else "FAIL"


def cfg_for(mode, args, out_path):
    # mode 必须进 cfg：旧版该形参**零引用**（函数体内只引用 args/cfg/out_path/workload），
    # 于是 cfg 里恒无档位，实现只能靠 run() 的 mode 形参自辨。
    cfg = {"corpus": args.corpus, "queries": args.queries, "out": out_path,
           "workers": args.workers, "k": workload.K_TOP, "mode": mode}
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
    #: ★本笔：**跨盘符安全**的「尽量相对、不行就绝对」。
    #: `os.path.relpath` 在 Windows 上对**不同盘符**的两条路径会抛
    #: `ValueError: path is on mount 'C:', start on mount 'E:'`（POSIX 只有一个根，
    #: 所以 CI 永远测不到）。而「impl 在系统临时目录、仓在另一个盘」是常态
    #: （本机 C:\Users\…\Temp vs E:\…），于是整份 runner 直接崩在打印这一行。
    #: 语义不变：同一盘符下仍给相对路径（可读、可搬）；跨盘符退化为绝对路径。
    def _display_path(p):
        try:
            return os.path.relpath(p)
        except ValueError:
            return p

    _impl_disp = _display_path(os.path.abspath(args.impl))
    summary = {"name": args.name, "impl": _impl_disp,
               "caps": getattr(mod, "CAPS", {}), "modes": {}}
    print("IMPL %s NAME %s" % (_impl_disp, args.name))
    print("CAPS %s" % json.dumps(getattr(mod, "CAPS", {}), ensure_ascii=False, sort_keys=True))

    for mode in [m for m in args.modes.split(",") if m]:
        out_path = os.path.join(args.rawdir, "%s_out_%s.jsonl" % (args.name, mode))
        lines = []
        rec = {"mode": mode}
        try:
            r = mod.run(mode, cfg_for(mode, args, out_path))
            if not isinstance(r, dict):
                raise TypeError("mod.run 必须返回 dict，实得 %s" % type(r).__name__)
            carry_evidence(rec, r)
            rec["mode"] = mode
            rec["ok"] = bool(r.get("ok"))
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
        rec["mode"] = mode
        # 可判读的失败结论字段（旧版失败模式只有 ok=false，无结论字段、退出码恒 0）。
        rec["conclusion"] = conclusion_of(rec)
        lines.append("EVIDENCE carried=%s dropped=%s"
                     % (json.dumps(rec.get("carried_keys", []), ensure_ascii=False),
                        json.dumps(rec.get("dropped_keys", []), ensure_ascii=False)))
        # 证据行：整条记录（含引擎自报的每个键）逐字落原始文本，报告里的读数可指认。
        lines.append("REC %s" % json.dumps(rec, ensure_ascii=False, sort_keys=True))
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

    # 失败必须反映到退出码：旧版 main() 无 sys.exit ⇒ 全模式异常仍 EXIT=0。
    bad_modes = sorted(m for m, rec in summary["modes"].items()
                       if not isinstance(rec, dict) or rec.get("ok") is not True)
    bad_timing = sorted(k for k, v in summary.items()
                        if k.startswith("timing_") and isinstance(v, dict) and v.get("error"))
    if bad_modes or bad_timing:
        print("FAILED modes=%s timing=%s" % (json.dumps(bad_modes, ensure_ascii=False),
                                            json.dumps(bad_timing, ensure_ascii=False)))
        return 1
    print("ALL_MODES_OK %d" % len(summary["modes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
