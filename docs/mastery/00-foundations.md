# 00 — Foundations: The Concepts Beneath the Code

Every other chapter explains *what our code does*. This chapter explains the
**ideas the code is made of** — embeddings, chunking, reranking, HyDE, BM25,
decay math — assuming nothing. Each section ends with *"In Talos"*: where the
concept lives in our code and **why we chose what we chose**, with the eval
evidence. When a later chapter names a concept, it points back here as
`→ 00 §N`.

Read this chapter once, slowly, before chapter 02. After that you'll only come
back to look things up.

---

## §1 · How an LLM answers, and why RAG exists

An LLM (like `gpt-4o-mini`) is a next-token predictor. You hand it a **prompt**
(text), it generates a continuation one **token** at a time (a token ≈ ¾ of an
English word; "retrieval" is 2–3 tokens). Everything it can consider must fit
in its **context window** — a hard limit on prompt + answer size, measured in
tokens (tens of thousands to hundreds of thousands depending on the model).

Three properties drive our whole design:

1. **It only knows two things:** what was in its training data (frozen, generic,
   possibly stale) and what is in the prompt *right now*. It has never seen your
   workspace's PDFs or your channel's conversation.
2. **It answers fluently even when it shouldn't.** Given a question and no
   relevant material, it will produce a confident, plausible, wrong answer — a
   **hallucination**. The fix is not "a smarter model"; it is *putting the right
   material in the prompt*.
3. **Temperature** controls sampling randomness: `0` ≈ deterministic
   most-likely-token; higher = more varied. For grounded Q&A you want low
   temperature — creativity is a liability when the job is "report what the
   document says."

**RAG (Retrieval-Augmented Generation)** is the answer to (1) and (2): before
calling the LLM, *retrieve* the handful of document passages most relevant to
the question and paste them into the prompt, then instruct the model to answer
*from that context*. The model doesn't learn anything; we just control what it
reads. The entire quality of a RAG system therefore lives or dies on one
question — **did retrieval put the right passages in the prompt?** (Our
2026-07-02 live diagnosis proved this the hard way: weak answers traced to
boilerplate chunks winning retrieval, not to the model. See §12.)

**Streaming**: instead of waiting for the full answer, the API yields tokens as
they're generated. That's why `/ask` returns a `StreamingResponse` and why
"failure after the first token" needs its own signalling (`[ask:error]` — the
HTTP status is already sent).

**In Talos:** the LLM is built in `src/rag/generation.py` (`ChatOpenAI`,
temperature from `llm_temperature`, default 0.7 — conversational but still
grounded by the prompt's instructions). We reach it through an
**OpenAI-compatible endpoint**: the OpenAI client just POSTs to
`OPENAI_BASE_URL`, so pointing that at `https://openrouter.ai/api/v1` with an
OpenRouter key gives us `openai/gpt-4o-mini` (or any routed model) with zero
code change. The grounding instruction lives in `RAG_PROMPT`
(`src/config/prompts.py`).

---

## §2 · Embeddings — meaning as geometry

An **embedding model** turns a piece of text into a vector — a fixed-length
list of floats (ours: **384 dimensions**) — such that *texts with similar
meaning land near each other* in that vector space. "How do I prepare for a
system design interview?" and "steps to get ready for architecture interviews"
share almost no words, but their vectors are close. That is the whole trick:
**semantic search = geometry**.

Nearness is measured by **cosine similarity** (the angle between two vectors:
1.0 = same direction, 0 = unrelated). When vectors are **normalized** to length
1 first, cosine similarity equals a simple dot product — cheaper to compute at
scale, which is why we pass `normalize_embeddings=True` to our embedder.

Two facts with hard operational consequences:

- **Dimension is a contract.** A 384-dim embedder and a 1536-dim collection
  cannot talk — every insert/search fails deep inside the vector DB with an
  opaque error. This is why `_assert_collection_dim` exists (probe-embed a
  string, compare to the collection schema, fail loudly with instructions).
- **Embeddings are not interchangeable.** Vectors from model A are meaningless
  to a corpus embedded with model B — even at the same dimension, the spaces
  are different. **Changing the embedding model means re-embedding (re-ingesting)
  everything.** That cost is why an embedder swap is a *decision*, not a config
  flip (§5).

**Asymmetric embedders**: some retrieval models are trained to treat *queries*
and *passages* differently — the query gets an instruction prefix telling the
model "this is a search query, embed it for finding passages." bge is one of
these (§5). Forget the prefix and nothing errors — retrieval quality just
silently degrades. That's exactly the kind of trap this guide exists to name.

**In Talos:** embedders are built and cached in `src/rag/vector_store.py`
(`_build_embeddings`, `lru_cache` — a HuggingFace sentence-transformer costs
~3.5s to load from disk, unaffordable per-request). Current default:
`BAAI/bge-small-en-v1.5`, 384-dim, normalized, with `BGE_QUERY_INSTRUCTION` on
the query side only.

---

## §3 · Vector search and Milvus

A **vector database** stores millions of (vector, metadata) rows and answers
one query fast: *given this query vector, return the k nearest rows* —
**k-nearest-neighbour (kNN) search**, also called **dense retrieval** (dense =
the meaning is spread across all 384 numbers; contrast **sparse/lexical**
methods like BM25, §7, where each dimension is a literal word).

At scale, exact nearest-neighbour is too slow, so vector DBs build **ANN
(approximate nearest neighbour) indexes** — clever data structures (e.g. graph-
based HNSW) that trade a sliver of recall for orders-of-magnitude speed. You
don't tune this day-to-day; you just need to know the results are *near*-exact
and arrive already **sorted by similarity** (which our chat-selection math
exploits by using rank position instead of raw scores, §11).

**Metadata filtering** is the second job: every row carries scalar fields
(`workspace_id`, `source`, `file_id`, `chatroom_id`, `message_ids`) and a query
can say "nearest neighbours *among rows where* `workspace_id == X &&
source == "file"`". This is how one physical collection safely serves many
tenants and two content types.

**In Talos:** the DB is **Milvus** (self-hostable, first-class LangChain
support, string filter expressions). One collection — `talos_documents` — holds
**both** file chunks and chat-memory segments, discriminated by a `source`
field (`"file"` / `"chat"`) that every query must conjoin into its filter. We
run it with `enable_dynamic_field=True` (no fixed schema beyond the vector, so
metadata fields are just written per-row). Plumbing, the ORM bridge
monkeypatch, and the delete helpers live in `src/rag/vector_store.py`
(chapter 02); the filter-expression grammar we use is catalogued in chapter 06.

---

## §4 · Chunking — why, and why `by_title`

You can't embed a whole PDF as one vector (one vector can't represent 60 pages
of distinct topics, and the whole doc wouldn't fit the prompt anyway). So
documents are split into **chunks**; each chunk is embedded and stored as one
row; retrieval returns chunks, not documents. Chunking is where RAG systems
quietly die, because a chunk must satisfy two tensions at once:

- **Big enough to mean something.** A 67-character fragment ("3h", a heading, a
  TOC line) embeds to a vector near *everything vague* and carries no answer
  material.
- **Small and single-topic enough to be findable.** A chunk mixing three topics
  embeds to a mushy average and matches none of them well.

The classic naive approach — and **our original failure** — is
character-window splitting. `RecursiveCharacterTextSplitter(chunk_size=1000)`
sounds like "1000-char chunks," but the number is a **ceiling, not a target**:
it only *splits* pieces that are too big, it never *merges* pieces that are too
small. Our ingestion fed it one piece per PDF **element** (see below), so the
live corpus ended up as **1,778 fragments, median 67 chars, 22% boilerplate,
84 exact duplicates**. Retrieval then returned titles and TOC lines — the model
got ~125 tokens of noise as its "context" and answered thinly. That was the
root cause of the "RAG is weak" incident (§12).

The fix, **section-aware chunking (`by_title`)**: our PDF parser
(`unstructured`) doesn't return raw text — it returns typed **elements**
(`Title`, `NarrativeText`, `ListItem`, `Header`, `Footer`…). `chunk_by_title`
walks that element stream and **accumulates elements into one chunk per
document section**, starting a new chunk at each `Title`, up to a max size —
i.e. it *merges*, giving chunks that match the document's own structure. We
additionally **filter noise element types** (headers, footers, page numbers)
before chunking. Result on the live corpus: 1,778 fragments → **375 section
chunks**; boilerplate-in-top-5 went **0.13 → 0.000**; judged answer correctness
**+18.6 points from this change alone** — by far the largest single win in the
remediation (§12).

**In Talos:** `build_chunk_documents` in `src/processing/documents.py`
(chapter 04), gated by `chunking_strategy` (`by_title` is now the default;
`recursive` remains for comparison). Changing chunking rewrites the corpus →
requires re-ingest (`scripts/reingest_workspace_files.py`).

---

## §5 · Choosing the embedder: the MiniLM → bge story

Two model families star in our history; know them both by name:

- **`sentence-transformers/all-MiniLM-L6-v2`** ("MiniLM") — the ubiquitous
  default of tutorials: tiny (6 transformer layers), fast, 384-dim, trained for
  *general sentence similarity* (paraphrase detection). It was our original
  embedder, chosen for exactly those reasons: free, local, CPU-friendly.
- **`BAAI/bge-small-en-v1.5`** ("bge") — same size class, **same 384
  dimensions**, but trained *specifically for retrieval* (query→passage
  matching, contrastive training on retrieval datasets; the bge family sits far
  above MiniLM on retrieval benchmarks like MTEB). It is **asymmetric** (§2):
  the query side needs the exact prefix
  `"Represent this sentence for searching relevant passages: "` (from the BAAI
  model card); passages are embedded plain.

Why the swap was *worth it*: general-similarity models judge "do these two
sentences say the same thing," but retrieval needs "would this passage *answer*
this question" — a different, asymmetric relation, and what bge is trained for.
Why the swap was *cheap*: same 384 dimensions, so no collection schema change —
though the vectors still had to be regenerated (§2), which we did anyway
because `by_title` rewrote the chunks.

Measured effect: **+1.2 points** judged correctness on top of `by_title` —
modest, because fixing the chunks had already removed most of the damage, but
consistent, and it hardens the system for harder corpora. The alternatives we
weighed (nomic-embed-text, gte-small, OpenAI `text-embedding-3-small` via
OpenRouter at $0.02/M tokens) were all viable; bge-small won on
same-dim/local/free/CPU with a proven eval delta.

**Two historical bugs to remember** (both fixed, both instructive): the
HuggingFace branch of `vector_store.py` once **hardcoded MiniLM** and ignored
`config.embedding_model` — so setting `EMBEDDING_MODEL=bge...` silently did
nothing; and even once honored, bge without its query instruction silently
underperforms. Hence today's `_hf_embeddings_for`: model name contains `"bge-"`
→ `HuggingFaceBgeEmbeddings` with the instruction + normalization; anything
else → plain `HuggingFaceEmbeddings`.

---

## §6 · Reranking — bi-encoders, cross-encoders, and the burial problem

The embedder from §2 is a **bi-encoder**: query and passage are embedded
*independently*, and similarity is just vector geometry. That independence is
what makes search over millions of rows fast (passages are pre-embedded) — and
also what caps its accuracy: the model never reads the query and the passage
*together*, so it can't notice fine-grained interactions ("this passage
mentions interviews, but not *preparing* for them").

A **cross-encoder** does read them together: feed the pair `(query, passage)`
through one transformer, get one relevance score. Far more accurate — and far
too slow to run against a whole corpus, because nothing can be precomputed:
every passage costs a full model forward pass *per query*.

**Reranking** composes the two so you get both properties:

1. **Fetch wide** with the cheap bi-encoder: take the top `fetch_k = 50`
   candidates (not just the final 10).
2. **Rescore narrow** with the cross-encoder: score all 50 pairs, keep the best
   `top_k = 10`.

The wide fetch is the point, and it targets a real pathology we measured:
**burial**. With weak embeddings and noisy chunks, the *right* passage was
often at dense-rank 10–20 while boilerplate filled the top 5 (our worst probe
query had 5/5 boilerplate in the top-5, first substantive chunk at rank 10).
A reranker can only promote what's *in the pool* — with the old pool of 20 over
fragment chunks, the pool itself was saturated with noise and reranking
couldn't rescue it. After `by_title`+bge fixed the candidates, widening to
50→10 added a further **+1.8 points** end-to-end.

Hence the coupling rule you'll meet in `build_rag_pipeline`: the wide fetch
happens *only because* reranking is on (`dense_k = rerank_fetch_k if
use_reranking else retrieval_top_k`). Reranking off + `fetch_k` high = nothing;
reranking on + `fetch_k == top_k` = the cross-encoder just reorders the same
list, gaining little.

**Our cross-encoder:** `cross-encoder/ms-marco-MiniLM-L-6-v2` — a MiniLM-sized
model fine-tuned on **MS MARCO**, Microsoft's large public dataset of real
search queries with human-labelled relevant passages; it's *the* standard
training set for passage rerankers. Small enough for CPU, loaded once per
process (`_get_cross_encoder`, `lru_cache`).

---

## §7 · Lexical search and hybrid retrieval (BM25)

Before embeddings, search was **lexical**: score a document by the query words
it literally contains. **BM25** is the canonical formula (the guts of
Elasticsearch): term frequency (more hits = better, with diminishing returns) ×
inverse document frequency (rare words count more) × length normalization.

Lexical and semantic search fail differently, which is why combining them —
**hybrid retrieval** — can help: embeddings handle paraphrase ("prepare" ≈ "get
ready") but can smear over exact identifiers; BM25 nails exact tokens
(`RagConfig`, error codes, function names) but scores zero on synonyms. An
`EnsembleRetriever` runs both and fuses the ranked lists (ours weights them
50/50).

**In Talos it is effectively eval-only today:** BM25 needs the whole corpus
tokenized **in memory** to score against; production's corpus lives in Milvus,
and we don't maintain a parallel in-memory index. So `build_rag_pipeline`
builds the hybrid only when a `corpus` list is passed (the eval harness does;
production passes none and falls back to dense-only with a warning). Turning
`use_hybrid_retrieval` on in prod is therefore a silent no-op — a named trap.

---

## §8 · Query-side tricks: rewriting and HyDE

Both attack the same asymmetry: **users write short, vague, conversational
questions, but the corpus contains long declarative passages** — and the
retrieval geometry works best when the query looks like what it's trying to
find. Both cost **one extra LLM call per question** (latency + money), which is
why each sits behind its own config flag.

**Query rewriting** (`use_query_rewrite`): before retrieval, ask a small LLM to
rewrite the user's question into an explicit, self-contained search query
(expand pronouns, add implied terms — "how do I prep for it?" → "how to prepare
for a system design interview"). Cheap, low-risk, and it helps conversational
phrasing; it's ON in our current live profile. The trace records both
`original_query` and `rewritten_query` so you can always see what retrieval
actually searched for.

**HyDE — Hypothetical Document Embeddings** (`use_hyde`): a stranger, cleverer
idea (Gao et al., 2022). Don't embed the *question* — ask an LLM to
**hallucinate a plausible answer paragraph** first, and embed *that*. The fake
answer is wrong on facts, but it's *shaped* like a real answer passage — same
vocabulary, same register — so it lands nearer to true answer passages in
vector space than the bare question does. The hallucination never reaches the
user; it exists only as a search probe. Implementation:
`HypotheticalDocumentEmbedder` wraps the base embeddings; the generator runs at
temperature 0 with a 150-token cap (deterministic, cheap).

Note the design boundary in `RAGChain.__init__`: HyDE wraps **file** retrieval
only — chat-memory recall uses plain base embeddings, because
hypothetical-*document* expansion is tuned for corpus QA, and conversation
recall ("what did we decide about X?") doesn't benefit from hallucinating a
fake document.

---

## §9 · Contextual compression — trimming retrieved chunks

Even good chunks carry some irrelevant sentences into the prompt. **Contextual
compression** post-processes retrieved docs before they reach the prompt.
LangChain's `ContextualCompressionRetriever` wraps a base retriever with a
*compressor*; ours supports three (`compression_type`):

- **`embeddings`** — `EmbeddingsFilter`: re-score each retrieved doc against
  the query with the embedder, **drop** docs below
  `compression_similarity_threshold`. Cheap (no LLM), coarse (whole-doc
  drop, no editing). Threshold is a trap: 0.76 proved too aggressive for
  `text-embedding-3-small` and silently emptied the context.
- **`llm`** — `LLMChainExtractor`: an LLM rewrites each doc down to only its
  query-relevant sentences. Precise, but **one LLM call per retrieved doc** —
  ~10 extra calls per question at our top_k.
- **`pipeline`** — embeddings filter first (cheap, culls), then LLM extractor
  (expensive, trims survivors).

**Default: `none`**, deliberately — with section-sized chunks and a reranker,
the marginal cleanup rarely justifies the latency/cost. The machinery exists
(and is eval-sweepable) for when a future corpus needs it.

---

## §10 · The retrieval funnel, end to end

All of §§2–9 composes into one funnel per question — this is
`build_rag_pipeline` + `RAGChain` in one picture:

```
                     question
                        │
          [rewrite? §8]──→ explicit query
                        │
          [HyDE? §8]────→ hypothetical answer text
                        │  embed (bge + query instruction, §2/§5)
                        ▼
   Milvus kNN, filtered: workspace && source=="file" (§3)
     fetch dense_k = 50 (wide, because reranking is on, §6)
                        │
          [hybrid? §7]  (eval-only: fuse with BM25 50/50)
                        ▼
   cross-encoder rescores 50 pairs → keep top_k = 10 (§6)
                        │
          [compress? §9] (default: none)
                        ▼
      10 section chunks (§4)  +  chat memory (tiers, §11)
                        ▼
   RAG_PROMPT{context, history, question} → LLM stream (§1)
```

Every stage is a `RagConfig` knob (chapter 03), every stage's actual behavior
is recorded in `RagTrace` (chapter 02), and the same funnel object is built by
production and the eval harness — which is what makes eval evidence binding on
production behavior (§12).

---

## §11 · The chat-memory math: rank relevance, decay, Jaccard

Chat memory (chapter 02's `chat_selection.py`) re-ranks recalled conversation
segments with three small pieces of math. None is exotic; know what each is
*for*:

- **Rank-based relevance, `1/(1+rank)`.** Milvus returns candidates already
  sorted by similarity (§3). Using each candidate's *position* (rank 0 → 1.0,
  rank 1 → 0.5, rank 2 → 0.33…) instead of its raw similarity score makes the
  formula independent of which distance metric the collection uses — raw scores
  change meaning across metrics; positions don't.
- **Exponential time decay with a half-life.** `0.5 ** (age_hours /
  half_life)`: a segment one half-life old (ours: 168h = one week) keeps 50% of
  its weight, two half-lives 25%, etc. — the standard "radioactive decay" curve
  for "recent conversation matters more." The **floor** (0.25) rescales decay
  into `[0.25, 1.0]` so a very old but uniquely relevant segment is dampened,
  never erased — without the floor, month-old decisions would become
  unrecallable no matter how relevant.
- **Jaccard similarity for redundancy.** `|A ∩ B| / |A ∪ B|` over the two
  segments' word sets — the fraction of shared vocabulary, 0 (disjoint) to 1
  (identical). Selection walks candidates best-first and skips any whose
  Jaccard overlap with an already-picked segment exceeds 0.6 — near-duplicate
  segments (retries, repeated announcements) would otherwise fill all k slots
  with one fact.

Final score: `relevance × (floor + (1-floor) · decay)` — relevance scaled by
recency, then greedy pick with redundancy skip, down to k.

---

## §12 · How we know any of this works: the eval story

Claims above like "+18.6 points" come from a specific methodology. Know it —
it's the difference between "we think it's better" and "we measured it," and
it's a viva centerpiece.

- **Gold labels.** 83 questions over the live PDF corpus, each labelled with
  the *pages* that contain the answer (page-level gold), questions
  paraphrase-constrained so lexical overlap can't fake success.
- **Judged correctness** (the headline metric). For each question, the full
  production pipeline produces an answer; a strong LLM **judge** scores it
  against the gold answer material. This is an **end-to-end** metric — it
  catches failures anywhere in the funnel.
- **Ablation.** Change **one variable per arm** (chunking alone, then +bge,
  then +rerank widening), measure each arm, attribute the delta to the change.
  That's how we can say `by_title` alone was +18.6 and bge +1.2 — not "the
  bundle helped."
- **Statistical significance.** Winning arm vs baseline tested with paired
  stats under **Holm correction** (an adjustment for testing multiple arms —
  it keeps you from cherry-picking the one arm that got lucky); winner A2 at
  p≈2.2e-5, i.e. essentially impossible by chance.
- **Beware proxy metrics.** We also measured **page-recall** ("did any
  retrieved chunk come from a gold page?") — and it *misled*: fragment
  chunking scored *higher* on page-recall (many tiny chunks per page ⇒ easy to
  hit the page) while producing *worse answers*. The judged end-to-end metric
  caught what the proxy hid. Lesson: optimize the metric that matches the goal.
- **eval == ship.** The harness imports and runs the *production*
  `build_chunk_documents`, `build_rag_pipeline`, and `RAG_PROMPT` — not a
  reimplementation. A toggle changes both worlds at once, so an eval result is
  evidence about production, not about a lookalike. (Chapter 05 walks the
  harness.)

Headline result (2026-07-03 remediation): judged correctness **0.657 → 0.855**;
boilerplate-in-top-k 0.13 → 0.000; corpus 1,778 fragments → 375 section chunks.
Full report: `evaluation/live_pdf_eval/REPORT.md`.

---

## §13 · Sixty seconds of infrastructure concepts

These appear throughout chapters 02/04/06; here's the minimum mental model:

- **Event loop vs threads.** FastAPI runs `async` handlers on one event loop —
  a single thread cooperatively switching between requests at every `await`.
  Blocking work (loading a model for seconds, sync DB calls, a sync LLM stream)
  **freezes every request** if run on the loop. The two escape hatches you'll
  see: `asyncio.to_thread(fn)` (run a sync function on a worker thread) and
  `iterate_in_threadpool(gen)` (consume a sync generator from async code).
  Corollary: sync SQLAlchemy `Session` inside threads, `AsyncSession` on the
  loop — never crossed.
- **Task queue & cron (taskiq + Redis).** Work that shouldn't happen inside an
  HTTP request (indexing chat, processing uploads) is enqueued to **Redis
  Streams** and executed by a separate **worker** process; a **scheduler**
  process enqueues cron ticks (chat indexing every 5 min). Redis Streams give
  **at-least-once** delivery — a task may run twice after a crash, so tasks
  must be **idempotent** (safe to re-run: hence "purge before re-ingest"
  patterns in the indexer).
- **Socket.IO rooms.** Realtime chat: each client socket joins room
  `channel:{id}`; an emit to the room reaches every member. The
  `AsyncRedisManager` relays emits across processes so an HTTP handler in one
  worker can reach sockets connected to another.
- **uuid7.** A UUID variant whose leading bits encode the timestamp —
  sortable-by-creation-time, unlike random uuid4. We mint one per `/ask` as
  `request_id`, the correlation key across trace, logs, and broadcast.
- **Presigned URLs (MinIO/S3).** Object storage can hand out a time-limited
  signed URL so a browser downloads directly from storage without the app
  proxying bytes.

---

## §14 · Pocket glossary

| Term | One-liner |
|---|---|
| token | LLM text unit, ≈ ¾ word; context window & costs are counted in these |
| context window | hard cap on what an LLM can read+write per call |
| hallucination | fluent answer fabricated without supporting material |
| RAG | retrieve relevant passages, paste into prompt, then generate |
| embedding | fixed-length float vector encoding a text's meaning (§2) |
| cosine similarity | closeness of two vectors; = dot product when normalized |
| dense retrieval | kNN search over embeddings (§3) |
| ANN index | approximate-nearest-neighbour structure making kNN fast |
| Milvus | our vector database; one collection, `source`-discriminated |
| chunk | the unit of ingestion/retrieval; one embedded row (§4) |
| `by_title` | section-aware chunking over unstructured's typed elements (§4) |
| element | typed piece of a parsed PDF (Title, NarrativeText, Footer…) |
| MiniLM | all-MiniLM-L6-v2 — old general-similarity embedder, 384-dim (§5) |
| bge | BAAI/bge-small-en-v1.5 — retrieval-trained embedder, 384-dim, needs query prefix (§5) |
| bi-encoder | embeds query & passage separately; fast, less accurate (§6) |
| cross-encoder | scores (query, passage) jointly; accurate, slow → rerank only (§6) |
| reranking | fetch wide (50) with bi-encoder, rescore & keep 10 with cross-encoder (§6) |
| burial | right passage exists but sits below the fetch cutoff (§6) |
| BM25 | lexical (word-match) ranking; hybrid = BM25 + dense fused (§7) |
| query rewrite | LLM turns a vague question into an explicit search query (§8) |
| HyDE | embed a hallucinated hypothetical answer instead of the question (§8) |
| contextual compression | trim/drop retrieved docs before the prompt (§9) |
| half-life decay | weight = 0.5^(age/half_life); recency curve for chat memory (§11) |
| Jaccard | set overlap |A∩B|/|A∪B|; our near-duplicate detector (§11) |
| judged correctness | LLM-judge score of end-to-end answers vs gold (§12) |
| ablation | change one variable per arm to attribute effect (§12) |
| eval == ship | harness runs production code paths, so results bind (§12) |
| at-least-once | queue may re-deliver; tasks must be idempotent (§13) |
| uuid7 | time-ordered UUID; our per-request correlation id (§13) |

---

## §15 · Self-test

1. **Why does RAG exist at all — what two LLM limitations does it patch?** The
   model only knows training data + the prompt, and it hallucinates fluently
   when the prompt lacks the answer. RAG controls what's in the prompt.
2. **You switch `EMBEDDING_MODEL` to a 768-dim model. What two things must
   happen before retrieval works again?** The collection must be recreated at
   768 dims, and every document re-embedded/re-ingested — old vectors are in a
   different space. (`_assert_collection_dim` is what catches you if you
   forget.)
3. **Why fetch 50 candidates when the prompt only gets 10?** The bi-encoder's
   top-10 is often wrong (burial); the cross-encoder can promote a rank-40
   chunk into the final 10 — but only if it's in the pool.
4. **Your teammate proposes turning on `use_hybrid_retrieval` in production to
   improve exact-name matching. What happens?** Nothing — no in-memory corpus
   is passed in production, so `build_rag_pipeline` logs a warning and stays
   dense-only. Hybrid is eval-only today.
5. **What is HyDE embedding, if not the question?** An LLM-hallucinated
   hypothetical *answer* paragraph — factually wrong, but shaped like real
   answer passages, so it lands closer to them in vector space.
6. **Chunking `by_title` beat the embedder swap 18.6 points to 1.2. What's the
   general lesson?** Garbage chunks poison every downstream stage; fix what the
   vectors *represent* before upgrading how they're computed.
7. **Page-recall went up while answers got worse. How?** Fragment chunking hits
   gold *pages* easily (many tiny chunks) while delivering no answer *material*
   — a proxy metric optimized past the actual goal.
8. **Why does the bge query instruction exist, and what happens without it?**
   bge is trained asymmetrically — queries need the "Represent this sentence
   for searching…" prefix to land in passage space. Without it: no error,
   silently worse retrieval.
