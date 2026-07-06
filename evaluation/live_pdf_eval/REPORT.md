# Live-PDF Retrieval Ablation — Results (2026-07-03)

## Setup

**Substrate.** The workspace's real corpus: a private ~90-page engineering/interview
preparation guide (filename withheld; local git-ignored copy at `data/guide.pdf`).
This is the same document whose live Milvus ingestion produced 1,778 element-level
fragments (median 67 chars) — the diagnosed root cause of weak @ai answers
(`docs/audits/2026-07-02-rag-retrieval-quality-findings.md`).

**Questions.** 83 LLM-authored, LLM-reviewed questions with reference answers and
page-level gold labels (`questions.json`), built under a paraphrase constraint to
avoid lexical-overlap leakage. Gold is page-level so it stays valid across arms
whose chunking differs.

**Pipeline.** Eval == ship: chunking via production `build_chunk_documents`,
retrieval via production `build_rag_pipeline`, answers via production `RAG_PROMPT`.
Only substitution: `InMemoryVectorStore` for Milvus (same cosine geometry; backend
not under test).

**Models.** Generation `openai/gpt-4o-mini`, judge `openai/gpt-4o` (both via
OpenRouter); embeddings all-MiniLM-L6-v2 vs BAAI/bge-small-en-v1.5 (CPU);
reranker cross-encoder/ms-marco-MiniLM-L-6-v2.

## Phase 1 — retrieval sweep (48 arms × 83 questions, metrics-only)

Corpus shape per chunking arm:

| chunking | chunks | median len |
|---|---|---|
| recursive (live today) | 1,778 | 67 |
| by_title | 375 | 440 |
| by_title_prefix | 375 | 463 |

Highlights (full table in `results/phase1.log`, raw rows in `results/retrieval_sweep.json`):

- **Boilerplate in retrieved top-k: 9–13% on every recursive arm; 0.000 on every
  by_title arm.** The hygiene fix eliminates the boilerplate-wins pathology outright.
- Page-recall is high everywhere (0.81–0.95) and slightly *higher* for recursive —
  a metric artifact: fragments from the right page count as recall but carry no
  usable content. Phase 2 (judged answers) is the decisive metric.
- top_k=10 beats top_k=5 consistently (+0.03–0.05 page-recall).
- by_title_prefix failed its pre-set bar (>0.02 page-recall over plain by_title) → dropped.
- fetch_k: 50 chosen (minilm 0.892@50 vs 0.861@20; bge tied 0.892 across 20/50/100 —
  aligned on 50 for a single shippable default).
- Sweep surprise: dense-only k=10 out-recalled rerank arms on page-recall
  (0.922 vs 0.892 on by_title/bge) → tested end-to-end as arm A4.

## Phase 2 — judged end-to-end arms (5 arms × 83 questions)

Correctness = gpt-4o judge score vs reference answer, paired per question.

| arm | config | correctness | Δ vs A0 | Wilcoxon p | Holm p | effect r |
|---|---|---|---|---|---|---|
| A0_live_baseline | recursive + MiniLM, rerank 20→5, rewrite on | 0.657 | — | — | — | — |
| A1_hygiene | by_title + MiniLM, rerank 50→10, rewrite on | 0.843 | +0.186 | 8.2e-06 | 2.5e-05 | 0.79 |
| **A2_hygiene_bge** | **by_title + bge, rerank 50→10, rewrite on** | **0.855** | **+0.198** | **5.5e-06** | **2.2e-05** | **0.81** |
| A3_hygiene_bge_raw | A2 without query-rewrite | 0.849 | +0.192 | 3.3e-05 | 6.6e-05 | 0.67 |
| A4_hygiene_bge_dense | A2 without reranker | 0.837 | +0.180 | 3.8e-05 | 6.6e-05 | 0.64 |

Raw per-question rows: `results/judged_arms.json` — **kept git-ignored** (answers
quote the private document); this table + `results/cache/` locally are the record.

## Winners + decision rule

Decision rule (pre-stated in the plan): highest judged correctness; ties broken
toward the simpler/cheaper config. **A2 wins.** Component reading:

- **Chunk hygiene is the dominant fix**: +18.6 points alone (A1), consistent with
  the diagnosis that fragmentation — not the reranker or the LLM — was the binding
  failure.
- **bge-small adds a small consistent lift** (+1.2 over A1) and dominates MiniLM
  on every phase-1 retrieval metric (burial 0.096 vs 0.120 dense@5).
- **Reranking stays on**: A2 0.855 > A4 0.837 end-to-end (the phase-1 page-recall
  edge for dense-only did not survive judged evaluation).
- **Query rewrite stays on** (default already True): +0.006 over A3 — marginal
  here (standalone questions), retained for the conversational /ask path where
  v7 showed rewrite's real value (+0.41 recall@5 on follow-ups).

## Recommended defaults (Task 6)

```python
retrieval_top_k: int = 10        # was 5
rerank_fetch_k: int = 50         # was 20
chunking_strategy: str = "by_title"   # was "recursive"
# chunk_prepend_section_title stays False (failed its bar)
# use_reranking / use_query_rewrite stay True (defaults unchanged)
```

Plus env (local stacks): `EMBEDDING_PROVIDER=huggingface
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5` (config defaults for embedding stay
OpenAI per plan — API deployments unaffected). Requires re-ingest (chunking +
embedder both change vectors; same 384-dim collection).

## Honest caveats

- Questions and judge are both LLMs (gpt-4o) — no human labels. The paraphrase
  constraint + independent review pass mitigate lexical leakage but don't replace
  human qrels (v7 carries that rigor on public benchmarks).
- Single corpus, single domain; magnitudes are specific to this document's
  pathology. The direction (hygiene ≫ embedder > rerank/rewrite) should transfer;
  the +19.8 headline number shouldn't be quoted as general.
- InMemoryVectorStore stands in for Milvus (identical cosine ranking on 375–1,778
  vectors; index-level differences negligible at this scale).
- A0 used judge-blind identical prompts/temperature; still, judge-family overlap
  (gpt-4o judging gpt-4o-mini answers) can compress differences — it cannot
  manufacture the baseline gap, which is the headline claim.
- Phase-2 arms fixed use_hyde=False (v7: situational, TOST-equivalent); the live
  USE_HYDE env toggle is unaffected by this eval.
