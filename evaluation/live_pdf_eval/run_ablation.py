"""Retrieval ablation on the REAL substrate (the private guide PDF (data/guide.pdf, git-ignored)).

Phase 1 (CPU-only, free): full retrieval sweep —
  chunking {recursive, by_title, by_title_prefix} x embedder {minilm, bge}
  x rerank {off, on(fetch_k in 20/50/100)} x top_k {5, 10}
Metrics per question: page_recall@top_k, first_gold_rank (wide k=100 dense,
burial diagnosis), boilerplate_rate@top_k.

Phase 2 (OpenRouter, judged): 4 arms end-to-end through the production
RAGChain-equivalent (build_rag_pipeline + RAG_PROMPT), gpt-4o-mini generation,
gpt-4o correctness judge vs the reference answer. Paired stats.

Eval == ship: chunking and retrieval are the production functions; the only
substitution is InMemoryVectorStore for Milvus (same cosine geometry; the
vector backend is not under test). Run:
  CUDA_VISIBLE_DEVICES="" PYTHONPATH=src:tests/rag_evaluation uv run python evaluation/live_pdf_eval/run_ablation.py [--phase 1|2] [--limit N]
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from common import (GEN_MODEL, JUDGE_MODEL, PDF_PATH, boilerplate_rate,
                    first_gold_rank, load_questions, openrouter_chat,
                    page_recall_at_k)

RESULTS = HERE / "results"
CHUNKINGS = ["recursive", "by_title", "by_title_prefix"]
EMBEDDERS = {"minilm": "sentence-transformers/all-MiniLM-L6-v2",
             "bge": "BAAI/bge-small-en-v1.5"}
FETCH_KS = [20, 50, 100]
TOP_KS = [5, 10]
BASE_META = {"workspace_id": "eval", "file_id": "eval", "filename": "guide.pdf"}


def rag_config(chunking: str):
    from config import RagConfig
    strategy = "by_title" if chunking.startswith("by_title") else "recursive"
    return RagConfig(chunking_strategy=strategy,
                     chunk_prepend_section_title=chunking == "by_title_prefix")


def build_corpus(elements, chunking: str):
    from processing.documents import build_chunk_documents
    return build_chunk_documents(elements, base_metadata=BASE_META, config=rag_config(chunking))


def build_store(chunks, embedder_key: str):
    from langchain_core.vectorstores import InMemoryVectorStore
    from rag.vector_store import _build_embeddings
    emb = _build_embeddings("huggingface", EMBEDDERS[embedder_key], None)
    return InMemoryVectorStore.from_documents(chunks, embedding=emb)


def retriever_for(store, *, top_k, use_rerank, fetch_k):
    from config import RagConfig
    from rag.retrieval.retrievers import build_rag_pipeline
    cfg = RagConfig(retrieval_top_k=top_k, use_reranking=use_rerank,
                    rerank_fetch_k=fetch_k, use_hyde=False, use_query_rewrite=False,
                    use_hybrid_retrieval=False)
    return build_rag_pipeline(cfg, store, corpus=None)


def phase1(questions):
    from unstructured.partition.auto import partition
    elements = partition(filename=PDF_PATH, strategy="fast")
    rows = []
    for chunking in CHUNKINGS:
        chunks = build_corpus(elements, chunking)
        print(f"[{chunking}] {len(chunks)} chunks, "
              f"median len {sorted(len(c.page_content) for c in chunks)[len(chunks)//2]}")
        for emb_key in EMBEDDERS:
            store = build_store(chunks, emb_key)
            # wide-k dense ranking once per question (burial diagnosis, rerank-free)
            wide = {q["id"]: store.similarity_search(q["question"], k=100) for q in questions}
            arms = [(False, 0, k) for k in TOP_KS] + [
                (True, f, k) for f, k in itertools.product(FETCH_KS, TOP_KS)]
            for use_rerank, fetch_k, top_k in arms:
                ret = retriever_for(store, top_k=top_k,
                                    use_rerank=use_rerank, fetch_k=fetch_k or top_k)
                for q in questions:
                    docs = ret.invoke(q["question"])
                    gold = set(q["gold_pages"])
                    rows.append({
                        "chunking": chunking, "embedder": emb_key,
                        "rerank": use_rerank, "fetch_k": fetch_k, "top_k": top_k,
                        "qid": q["id"],
                        "page_recall": page_recall_at_k(docs, gold, top_k),
                        "boiler_rate": boilerplate_rate(docs, top_k),
                        "first_gold_rank_topk": first_gold_rank(docs, gold),
                        "first_gold_rank_dense100": first_gold_rank(wide[q["id"]], gold),
                    })
                print(f"  {chunking}/{emb_key} rerank={use_rerank} fetch={fetch_k} k={top_k} done")
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "retrieval_sweep.json").write_text(json.dumps(rows, indent=1))
    summarize_phase1(rows)


def summarize_phase1(rows):
    import statistics as st
    keyf = lambda r: (r["chunking"], r["embedder"], r["rerank"], r["fetch_k"], r["top_k"])
    groups = {}
    for r in rows:
        groups.setdefault(keyf(r), []).append(r)
    print(f"\n{'arm':60s} {'recall':>7s} {'boiler':>7s} {'burial>k':>8s}")
    for key in sorted(groups):
        g = groups[key]
        rec = st.mean(x["page_recall"] for x in g)
        boil = st.mean(x["boiler_rate"] for x in g)
        buried = sum(1 for x in g if x["first_gold_rank_topk"] is None) / len(g)
        print(f"{str(key):60s} {rec:7.3f} {boil:7.3f} {buried:8.3f}")


JUDGED_ARMS = {
    # arm -> (chunking, embedder, fetch_k, top_k, use_rewrite, use_rerank)
    # HyDE is deliberately EXCLUDED from judged arms: v7 showed it situational
    # (TOST-equivalent on FiQA) and wiring it here would swap the query embedder;
    # the live env keeps its independent USE_HYDE toggle.
    # Parameters set from the FULL phase-1 sweep (results/phase1.log, n=83):
    # by_title_prefix failed its >0.02 bar vs plain by_title -> dropped;
    # top_k=10 beat 5 everywhere; fetch_k=50 for minilm (0.892 > 0.861@20),
    # 50 kept for bge too (recall tied 0.892 across 20/50/100 - aligned with
    # minilm for a single shippable default). A4 tests the sweep's surprise:
    # dense-only k=10 out-recalled rerank arms (0.922 vs 0.892 on by_title/bge).
    "A0_live_baseline":    ("recursive", "minilm", 20, 5, True, True),
    "A1_hygiene":          ("by_title", "minilm", 50, 10, True, True),
    "A2_hygiene_bge":      ("by_title", "bge", 50, 10, True, True),
    "A3_hygiene_bge_raw":  ("by_title", "bge", 50, 10, False, True),
    "A4_hygiene_bge_dense": ("by_title", "bge", 50, 10, True, False),
}


def phase2(questions):
    from eval_utils import JsonCache, judge_correctness  # tests/rag_evaluation on PYTHONPATH
    from config.prompts import RAG_PROMPT
    from unstructured.partition.auto import partition

    gen = openrouter_chat(GEN_MODEL)
    judge = openrouter_chat(JUDGE_MODEL)
    cache = JsonCache(RESULTS / "cache" / "judged.json")
    elements = partition(filename=PDF_PATH, strategy="fast")

    out = {}
    for arm, (chunking, emb_key, fetch_k, top_k, use_rewrite, use_rerank) in JUDGED_ARMS.items():
        chunks = build_corpus(elements, chunking)
        store = build_store(chunks, emb_key)
        from config import RagConfig
        from rag.retrieval.retrievers import build_rag_pipeline
        cfg = RagConfig(retrieval_top_k=top_k, use_reranking=use_rerank, rerank_fetch_k=fetch_k,
                        use_hyde=False, use_query_rewrite=False, use_hybrid_retrieval=False)
        ret = build_rag_pipeline(cfg, store, corpus=None)
        rewriter = openrouter_chat(GEN_MODEL) if use_rewrite else None

        arm_rows = []
        for q in questions:
            ck = f"{arm}::{q['id']}"
            if (hit := cache.get(ck)) is not None:
                arm_rows.append(hit); continue
            query = q["question"]
            if rewriter is not None:
                from config.prompts import QUERY_REWRITE_PROMPT
                # QUERY_REWRITE_PROMPT is a PromptTemplate with input_variables=["query"]
                # (verified against src/config/prompts.py — NOT "question" as the
                # brief's illustrative code assumed).
                query = str(rewriter.invoke(QUERY_REWRITE_PROMPT.format(query=query)).content)
            docs = ret.invoke(query)
            context = "\n\n".join(d.page_content for d in docs)
            # RAG_PROMPT is a ChatPromptTemplate with a chat_history placeholder
            msgs = RAG_PROMPT.format_messages(context=context, question=q["question"], chat_history=[])
            answer = str(gen.invoke(msgs).content)
            # eval_utils signature: judge_correctness(answer, reference, question, judge_llm)
            score, reason = judge_correctness(answer, q["reference_answer"], q["question"], judge)
            row = {"qid": q["id"], "arm": arm, "correct": score, "answer": answer, "reason": reason}
            cache.set(ck, row); arm_rows.append(row)
        cache.flush()
        out[arm] = arm_rows
        import statistics as st
        print(f"{arm}: correctness {st.mean(r['correct'] for r in arm_rows):.3f} (n={len(arm_rows)})")

    (RESULTS / "judged_arms.json").write_text(json.dumps(out, indent=1))
    from eval_utils import holm_bonferroni, paired_wilcoxon
    base = {r["qid"]: r["correct"] for r in out["A0_live_baseline"]}
    ps = []
    for arm in [a for a in JUDGED_ARMS if a != "A0_live_baseline"]:
        pair = [(base[r["qid"]], r["correct"]) for r in out[arm] if r["qid"] in base]
        stat = paired_wilcoxon([a for a, _ in pair], [b for _, b in pair])
        ps.append((arm, stat))
        print(f"{arm} vs baseline: {stat}")
    adj = holm_bonferroni([s["p"] for _, s in ps])  # paired_wilcoxon returns {stat, p, effect_r, n_nonzero}
    for (arm, _), p in zip(ps, adj):
        print(f"{arm}: Holm-adjusted p = {p:.2e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int, default=1, choices=[1, 2])
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    qs = load_questions()
    if args.limit:
        qs = qs[: args.limit]
    (phase1 if args.phase == 1 else phase2)(qs)
