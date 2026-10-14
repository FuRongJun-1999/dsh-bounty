"""确定性工作负载：合成语料 + 查询集 + BM25 检索（零 LLM、零网络、零随机时钟）。

评测契约见 harness/spec.md。本文件是「同一个任务」的唯一定义，四个实现（基线 +
三家引擎）都必须调用这里的纯函数完成检索，保证对照公平。
"""
import json
import os
import random

WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
         "mike november oscar papa quebec romeo sierra tango uniform victor whiskey "
         "xray yankee zulu anchor beacon canopy dagger ember falcon granite harbor "
         "ivory jigsaw kernel lantern marble nectar onyx pebble quartz ripple sapphire "
         "timber umbrella velvet walnut xenon yarrow zephyr amber basalt cobalt dune "
         "elm flint garnet hazel indigo jasper kelp lotus moss nimbus opal prism "
         "quill reed slate thistle umber vine willow").split()

TOPICS = ["t%02d" % i for i in range(20)]

K_TOP = 5


def _rng(seed):
    return random.Random(seed)


def build_corpus(path, n_docs=200, seed=20261014):
    """生成确定性语料：每篇 60-140 个词，开头一个主题词，其余从词表抽。"""
    r = _rng(seed)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for i in range(n_docs):
            topic = TOPICS[i % len(TOPICS)]
            body = [r.choice(WORDS) for _ in range(r.randint(60, 140))]
            text = topic + " " + " ".join(body)
            f.write(json.dumps({"id": "doc%04d" % i, "topic": topic, "text": text},
                               ensure_ascii=False, sort_keys=True) + "\n")
    return path


def build_queries(path, corpus_path, n_queries=40, seed=20261015):
    """生成确定性查询：每条 2-3 个词，全部取自某篇文档（保证有命中）。"""
    docs = load_corpus(corpus_path)
    r = _rng(seed)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for i in range(n_queries):
            d = docs[r.randrange(len(docs))]
            toks = d["text"].split()
            pick = [toks[0]] + r.sample(toks[1:], 2)
            f.write(json.dumps({"q": "q%03d" % i, "src": d["id"], "terms": pick},
                               ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_corpus(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_queries(path):
    return load_corpus(path)


# ---- 五个步骤的纯函数（基线直接调用；引擎实现把同一逻辑包进节点/任务）----

def step_load(corpus_path):
    return load_corpus(corpus_path)


def step_index(docs):
    from rank_bm25 import BM25Okapi
    tokenized = [d["text"].split() for d in docs]
    return {"docs": docs, "bm25": BM25Okapi(tokenized)}


def step_retrieve(index, queries, k=K_TOP):
    out = []
    for q in queries:
        scores = index["bm25"].get_scores(list(q["terms"]))
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], index["docs"][i]["id"]))
        out.append({"q": q["q"], "terms": q["terms"],
                    "ids": [index["docs"][i]["id"] for i in order[:k]]})
    return out


def step_verify(index, retrieved):
    by_id = {d["id"]: d for d in index["docs"]}
    out = []
    for r in retrieved:
        kept = []
        for did in r["ids"]:
            text = by_id[did]["text"]
            if all(t in text.split() for t in r["terms"]):
                kept.append(did)
        out.append({"q": r["q"], "terms": r["terms"], "ids": kept,
                    "dropped": len(r["ids"]) - len(kept)})
    return out


def step_emit(verified, out_path):
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for r in verified:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    return out_path


def steps_all(corpus_path, query_path, out_path, k=K_TOP):
    """参考实现（基线）：五步顺序执行，返回每步执行轨迹。"""
    trace = []
    docs = step_load(corpus_path); trace.append("load")
    index = step_index(docs); trace.append("index")
    queries = load_queries(query_path)
    retrieved = step_retrieve(index, queries, k); trace.append("retrieve")
    verified = step_verify(index, retrieved); trace.append("verify")
    step_emit(verified, out_path); trace.append("emit")
    return {"trace": trace, "verified": verified, "out": out_path}
