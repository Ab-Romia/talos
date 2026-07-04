# RAG Retrieval-Quality Findings — 2026-07-02

Consolidated output of 5 parallel investigations: retrieval-path code audit, v7 eval
evidence deep-read, embedding-upgrade research, chunk-hygiene research, and an
empirical probe of the live Milvus corpus (`talos_documents`, workspace "Romario",
the workspace guide PDF). Raw probe artifacts (census, classifications, per-query
retrieval + rerank results) saved in the session scratchpad
(`all_chunks.json`, `classification.json`, `retrieval_results.json`, `rerank_results.json`).

## Headline: the diagnosis changes

The working theory was "1,778 mechanical 1000-char chunks with boilerplate."
**Measured reality: the chunks are tiny fragments.** Census of all 1,778 file chunks:

- Length (chars): min=1, p25=25, **median=67**, p75=135, max=671, mean=102.7.
- 22.3% (396) classify as boilerplate (bare headings/labels, page numbers,
  symbol-heavy fragments like `3h`, `O(n)`, `Preparation required`).
- 84 chunks are exact duplicates of 19 strings (`"3h"` ×9, `"possible"` ×8, …);
  8.2% of the corpus sits in near-duplicate pairs (Jaccard>0.9).
- Zero sliding-window overlap artifacts — these are NOT 1000-char windows.

**Root cause (verified in code):** `src/processing/documents.py:38-64` builds one
LangChain `Document` per `unstructured` element, then runs
`RecursiveCharacterTextSplitter(chunk_size=1000, overlap=200)`. That splitter only
SPLITS documents larger than 1000 chars — it **never merges small ones**. A PDF
partitioned with `strategy="fast"` emits hundreds of one-line elements (headings,
table cells, list stubs), and every one of them becomes its own vector.
`chunk_size=1000` is a ceiling, not a target.

**Consequence for answer quality:** context delivered to the model is
`retrieval_top_k=5` × ~100 chars ≈ **~125 tokens** — about 0.1% of gpt-4o-mini's
128k window. Even perfect retrieval would hand the generator five sentence
fragments. This single mechanism explains "answers are weak / not grounded."

## Live retrieval probe (8 realistic queries, dense top-20 + rerank simulation)

| Query | boilerplate in top-5 | first substantive rank |
|---|---|---|
| system design preparation steps | **5/5** | 10 |
| two pointers / sliding window | 3/5 | 4 |
| array/string patterns | 1/5 | 1 |
| behavioral answer formula | 1/5 | 2 |
| other 4 queries | 0/5 | 1 |

- Burial is real but query-dependent: worst case top-5 is 100% heading fragments
  ("System design", "Preparation required" ×4).
- **Reranking the top-20 pool does NOT rescue it**: cross-encoder
  (ms-marco-MiniLM-L-6-v2) left boilerplate-in-top-5 unchanged in aggregate
  (10/40 → 10/40); the "system design" case stayed 5/5 boilerplate because the
  20-pool itself contains almost nothing substantive. The pool is
  saturated upstream — pool depth and chunk hygiene, not reranker quality, bind.

## Ranked findings

### F1 — Element-level fragmentation at ingest (dominant; code-small; needs re-ingest)
Mechanism above. `documents.py` also discards `el.category` (`:105-113`), so
Title/Header/Footer elements are indistinguishable from content downstream.
Fix direction (research-backed): filter noise categories, then use unstructured's
`chunk_by_title` (`max_characters≈800-1000`, `combine_text_under_n_chars≈150-250`,
`new_after_n_chars≈800`) so chunks are section-scoped, merged to real size, and
never span sections. Optionally prepend the section title to chunk text
(zero-cost contextual header; ablate it). Chroma's chunking eval says well-tuned
heuristic chunking ≈ semantic chunking — do not over-engineer.

### F2 — Rerank pool (20) and top_k (5) are too small for this corpus (config-only)
`rerank_fetch_k=20` over 1,778 chunks ≈ 1.1% of the corpus; the probe shows the
pool saturates with boilerplate and v7's rerank win used pool=50. `retrieval_top_k=5`
of fragment-sized chunks starves the prompt. Both fields are already in the
ai_settings `OVERRIDABLE` whitelist (top_k ≤50, fetch_k ≤100) — tunable today
without code. Post-hygiene values still need eval; interim bump is near-free
on tokens.

### F3 — Embedding model: all-MiniLM-L6-v2 is the weakest link after hygiene (code-small + re-embed)
- MTEB retrieval: bge-small-en-v1.5 ≈ 51.7 vs MiniLM clearly lower (~8-10 pts);
  a technical-domain benchmark showed a much larger domain gap (MiniLM family
  ~27 nDCG@10 vs bge-small 58.9).
- **Top pick: BAAI/bge-small-en-v1.5** — same 384-dim (no schema change), 33M
  params CPU-friendly, MIT, and it's what v7 validated locally. Requires the
  query-side instruction prefix ("Represent this sentence for searching relevant
  passages: ") — use `HuggingFaceBgeEmbeddings` or manual prefixing; getting this
  wrong silently degrades. Runner-up: nomic-embed-text-v1.5 (62.3 MTEB, 8k context,
  but 137M params, 768-dim, trust_remote_code).
- Milvus: dim is fixed at creation, but bge-small keeps 384 → same collection
  shape; vectors still must be re-embedded (drop or blue/green via collection
  alias; ~2k chunks = minutes on CPU).
- **Code trap found:** `vector_store.py:92-95` hardcodes MiniLM in the huggingface
  branch and ignores `config.embedding_model` — the trace misreports the embedder,
  and defaults (`embedding_provider="openai"`, 1536-dim) mismatch the live 384-dim
  collection if the env override is ever lost. Fix: honor `embedding_model`, assert
  collection dim at startup.
- OpenRouter **now serves embeddings** (`/embeddings`, incl.
  `openai/text-embedding-3-small` @ $0.02/M) — API embeddings are viable with the
  existing key (verify operationally before relying on it).

### F4 — v7 evidence does not cover the live regime; eval harness needs 4 additions before "eval==ship" ablation
v7's P1-P3 scripts bypassed the production pipeline (raw sentence-transformers +
bge-small, pool=50, clean multi-doc corpora). Confirmed transfers: rerank recovers
buried gold *when gold is in the pool*; rewrite fixes conversational queries; HyDE
situational. NOT covered: MiniLM-vs-bge head-to-head, boilerplate-polluted
single-PDF corpus, fetch_k=20, chunk-hygiene effects. To run the decisive ablation
on the real substrate, the harness needs:
1. an embedder gate in `run_eval.py` (currently hardcodes OpenAIEmbeddings at :205);
2. a question set + gold labels over the live PDF (synthesize_qa exists but draws
   vocab from gold chunks — must constrain for lexical gap, or judge-based gold);
3. wide-k dense-rank logging for all variants (burial diagnosis);
4. `rerank_fetch_k` as a sweep axis.
OpenRouter credits can drive generation + judges (no GPU juggling).

### F5 — Secondary traps (small, fix opportunistically)
- Reranker has no score floor — 5 slots always fill even when nothing is relevant
  (`retrievers.py:76-78`).
- Hybrid/BM25 is a silent no-op in prod (no corpus passed; flag not overridable
  yet shown in effective_config).
- HyDE uses the generic `web_search` prompt key and swaps the vectorstore's query
  embedder entirely (`query_processing.py:19-29`, `rag_chain.py:97-100`) — foot-gun
  on a technical corpus.
- Query rewrite discards the raw query entirely (`rag_chain.py:128-138`).
- `compression_similarity_threshold=0.76` calibrated for text-embedding-3-small;
  wrong for any 384-dim model if compression is ever enabled.
- Two dead/duplicate splitter definitions (`ingestion.py:56-61` unused on file path).

## Proposed remediation tracks (for scoping)

- **A. Chunk hygiene (F1)** — element filtering + `chunk_by_title` + re-ingest.
  Highest expected impact; code-small in `documents.py`.
- **B. Embedding swap (F3)** — bge-small-en-v1.5 + honor `embedding_model` +
  dim assert + re-embed. Second-highest impact; pairs naturally with A (one
  re-ingest covers both).
- **C. Pool/top_k retune (F2)** — fetch_k and top_k raised to eval-tuned values.
  Config-only; final values come from the ablation.
- **D. Eval-on-real-substrate (F4)** — harness gates + live-PDF question set +
  ablation grid (chunking × embedder × fetch_k/top_k × hyde/rewrite). This is
  the "eval == ship" gate for A-C defaults.
- **E. Hardening nits (F5)** — rerank floor, HyDE prompt/scope, config traps.

Recommended shape: build D's question set first (it validates everything),
then A+B together (single re-ingest), ablate via D, then set defaults + C, E
opportunistic.
