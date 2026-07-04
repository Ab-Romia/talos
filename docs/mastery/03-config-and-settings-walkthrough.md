# 03 — Config and Settings Walkthrough

This chapter covers the *configuration layer* of your RAG system: the static
defaults (`RagConfig`), the prompts, and the runtime override machinery that lets
a workspace admin retune the AI per-workspace and per-channel without a redeploy.
Every claim is grounded in the code. Line references are to the files on
`feature/chat-message-memory`.

There are **three layers of configuration**, resolved lowest-to-highest:

```
global_rag_config (env + defaults)  ->  workspace default (channel_id IS NULL)  ->  channel override
```

Layer 1 is `RagConfig` (`config/config.py`). Layers 2 and 3 live in the
`ai_settings` table and are merged by `resolve_ai_config` (`rag/ai_settings.py`)
into a *real* `RagConfig` copy, which every downstream `config=` seam already
honours. The HTTP surface for editing layers 2 and 3 is `settings_router.py`.

The underlying RAG/ML concepts each knob controls are explained once, in depth,
in `00-foundations.md`; this chapter only walks the code. Wherever a field's
meaning presumes a concept, you'll see a pointer like `(→ 00 §n)` — follow it
if the field name alone doesn't tell you what it's for.

Read the files in this order:

1. `config/prompts.py` — the two prompt templates (leaf).
2. `config/config.py` — `RagConfig`, the base layer.
3. `rag/ai_settings.py` — the override table, the patch schema, and resolution.
4. `rag/settings_router.py` — the endpoints that read/write overrides.

---

## `src/config/prompts.py`

**Job in one sentence:** define the two prompt templates — the retrieval query
rewriter and the answer prompt — as the single place their wording lives.

### `QUERY_REWRITE_PROMPT` — lines 9–17
A `PromptTemplate` with one input variable, `query`:

```
Rewrite the following question to be more specific and searchable for document retrieval.
Make it clearer and add relevant keywords, but keep the core intent.

Original Question: {query}

Rewritten Query:
```

**Its job:** feed the query rewriter (`get_query_rewriter` = this prompt piped
into the LLM). It asks the model to expand the raw question with keywords while
preserving intent, producing a string that retrieves better than the bare
question — the query-rewrite trick that closes the gap between vague user
phrasing and the corpus's declarative prose (→ 00 §8). It runs only when
`config.use_query_rewrite` is on.

### `RAG_PROMPT` — lines 19–33
A `ChatPromptTemplate` with three parts, each doing a distinct job:

```
("system",  "You are a helpful AI assistant. Use the following context to answer the question.
             If you cannot answer based on the context provided, say so clearly.
             Context:
             {context}")
MessagesPlaceholder(variable_name="chat_history")
("human",   "{question}")
```

- **System message (lines 21–29):** sets the assistant's role, injects the
  retrieved `{context}`, and — importantly — instructs it to *say so clearly* when
  the context doesn't answer the question. That single sentence is your main guard
  against hallucination: it licenses "I don't know" instead of invention.
- **`MessagesPlaceholder("chat_history")` (line 30):** where the tier-1 injected
  tail lands. `RAGChain` fills this slot with the un-indexed conversation
  (`PreparedAsk.history`). It sits *between* the context and the new question so
  the model reads: instructions+context → prior turns → the current question.
- **`("human", "{question}")` (line 31):** the current user question, last.

**Why the ordering matters:** `RAGChain._fill_trace` and `stream_answer` both call
`RAG_PROMPT.format_messages(...)` / `.invoke(...)` with exactly
`{context, question, chat_history}` (rag_chain.py lines 196–199, 257–261). The
variable names here are a hard contract with those call sites.

**Gotcha:** if you rename `context`, `question`, or `chat_history`, you must update
`RAGChain` in the same commit — the prompt and the chain are coupled by these
names, and a rename fails at render time, not import time.

### Owner self-test — prompts
1. **What stops the model from inventing an answer when retrieval finds nothing?**
   The system message tells it to say so clearly when it cannot answer from the
   context.
2. **Where does the un-indexed chat tail get injected into the prompt?** The
   `MessagesPlaceholder("chat_history")`, between the context and the new question.
3. **If you rename the `{context}` variable, what breaks?** `RAGChain`'s
   `stream_answer`/`_fill_trace` calls that pass `context=...` — the prompt and
   chain are coupled by variable name.

---

## `src/config/config.py`

**Job in one sentence:** define `RagConfig`, the base configuration layer — every
tunable default for the whole RAG system, loaded from env/`.env` via
pydantic-settings, exposed as the process-wide singleton `global_rag_config`.

### `CompressionType` — lines 10–14
A `str` `Enum`: `LLM`, `EMBEDDINGS`, `PIPELINE`, `NONE`. Being a `str` enum means
the value round-trips cleanly to/from env strings and JSON (`compression_type`
serializes as `"none"`, etc. — `_fill_trace` reads `.value`).

### `RagConfig` fields, grouped by concern
`RagConfig(BaseSettings)` (line 17). Each field is a class attribute with a typed
default; pydantic-settings overrides any of them from the environment.

**Model / API (lines 18–22)**
- `openai_api_key: SecretStr | None` — wrapped in `SecretStr` so it never prints
  in logs or `repr`.
- `openai_model` = `"gpt-4o-mini"` — the generation (and, today, rewrite/HyDE) model.
- `embedding_model` = `"text-embedding-3-small"`, `embedding_provider` = `"openai"` —
  which vendor/model turns text into vectors. Both are load-bearing together:
  embeddings from different models aren't interchangeable, so changing either
  means the whole corpus must be re-embedded/re-ingested, not just reconfigured
  (→ 00 §2, §5 for the MiniLM→bge story and why bge won).

**Milvus (lines 24–26)**
- `milvus_host`, `milvus_port` (19530), `milvus_collection_name`
  (`"talos_documents"`). The last is the single collection both files and chat
  memory share (see `WORKSPACE_COLLECTION`) — the vector database that answers
  "nearest rows to this vector" (kNN/dense retrieval) and filters by metadata
  like `workspace_id`/`source` (→ 00 §3).

**Retrieval tuning (lines 28–53)** — these carry eval provenance in their comments:
- `retrieval_top_k` = 10 (line 31). Comment: 10 beat 5 by +0.03–0.05 page-recall
  in the live-PDF ablation. This is the *narrow* final count the model actually
  sees.
- `rerank_fetch_k` = 50 (line 39). The wide candidate pool the dense stage fetches
  *before* the cross-encoder narrows to `retrieval_top_k`. Comment: widening here
  is what lets reranking improve recall rather than merely reorder; ignored when
  `use_reranking` is False. Eval picked 50 over 20. The two fields are a coupled
  pair — fetch wide with the cheap bi-encoder, then rescore narrow with the
  cross-encoder — because the right passage is often "buried" outside a narrow
  fetch and a reranker can only promote what's in its pool (→ 00 §6).
- `use_hybrid_retrieval` = False (line 40) — BM25 hybrid, effectively eval-only
  (needs an in-memory corpus). BM25 is lexical (word-match) search, complementary
  to embeddings' semantic match; flipping this on in production is a silent
  no-op today (→ 00 §7).
- `use_reranking` = True (line 41) — gates the cross-encoder rescoring pass
  described above (→ 00 §6).
- `use_hyde` = True, `use_query_rewrite` = True (lines 46–47). Comment (42–45):
  each adds an LLM call per query; gated so they can be turned off; default keeps
  the prior always-on behaviour. `use_hyde` embeds an LLM-hallucinated
  hypothetical answer instead of the raw question (the fake answer never reaches
  the user — it's only a search probe); `use_query_rewrite` expands a short,
  vague question into an explicit search query. Both target the same mismatch:
  user questions are short and conversational, corpus passages are long and
  declarative (→ 00 §8).
- `compression_type` = `NONE` (line 49); `compression_similarity_threshold` = 0.76
  (line 53). Comment: configurable so the eval calibrates it and prod ships what
  eval swept; 0.76 was too aggressive for `text-embedding-3-small`. Contextual
  compression trims or drops retrieved chunks before they reach the prompt; there
  are three compressor types (`embeddings`/`llm`/`pipeline`), and the similarity
  threshold is specifically the `embeddings` compressor's drop cutoff — set it
  too high (as 0.76 was here) and it silently empties the context (→ 00 §9).

**Chunking (lines 55–67)**
- `chunk_size` = 1000, `chunk_overlap` = 200.
- `chunking_strategy` = `"by_title"` (line 62). Comment (57–61): `"recursive"`
  fragmented elements into ~67-char chunks with 9–13% boilerplate; `"by_title"`
  merges into ~440-char section chunks with 0 boilerplate and +18.6pt judged
  correctness. The core distinction: `chunk_size` for `"recursive"` is a
  *ceiling, not a target* — it only splits oversized pieces, never merges
  undersized ones — whereas `"by_title"` walks the parser's typed elements and
  *merges* them into one chunk per document section, which is what fixes the
  too-small-to-mean-anything fragments (→ 00 §4).
- `chunk_prepend_section_title` = False (line 67). Comment: ablated and failed its
  pre-set bar, stays off.

**Chat-memory indexing + recall (lines 69–90)** — the tier-2 machinery:
- `chat_index_interval_minutes` = 5, `chat_index_grace_seconds` = 300,
  `chat_index_batch_size` = 500, `chat_index_max_batches` = 10 (lines 72–77). The
  cron only embeds messages older than the grace window so live messages still in
  the un-indexed tail aren't indexed prematurely (comment 70–71).
- `chat_recall_k` = 3 (line 78) — final segments kept after re-ranking.
- `chat_context_cap` = 50 (line 79) — the tier-1 tail COUNT bound (used by
  `_load_unindexed_tail`) — a cap on *number of messages*, not tokens.
- `chat_context_char_budget` = 16000 (line 83) — the tier-1 tail LENGTH bound
  (≈4k tokens, tokenizer-free): a burst of huge un-indexed messages can't blow
  the context window; the newest message is always kept whole. Characters are
  used as a cheap proxy for tokens (a token is roughly ¾ of a word) precisely to
  avoid running a tokenizer just to bound what fits in the LLM's context window
  (→ 00 §1).
- `chat_segment_gap_minutes` = 30, `chat_segment_max_messages` = 12 (lines 81–84)
  — a conversation segment (the embedded unit) closes on an inactivity gap or a
  size cap.
- `chat_recall_fetch_k` = 10 (line 88) — the wider pool fetched before chat
  re-ranking, the same fetch-wide/rescore-narrow shape as `rerank_fetch_k`
  above (→ 00 §6).
- `chat_decay_half_life_hours` = 168.0 (one week, line 89) — the exponential
  time-decay half-life: a segment this many hours old keeps half its relevance
  weight, so recent conversation is favored without erasing old-but-relevant
  segments (→ 00 §11).
- `chat_recall_overlap_threshold` = 0.6 (line 90) — the Jaccard redundancy floor:
  candidates whose word-set overlap with an already-picked segment exceeds this
  are skipped, so near-duplicate segments don't fill all the recall slots
  (→ 00 §11).

**LLM behaviour (lines 92–93)**
- `llm_temperature` = 0.0 (deterministic), `llm_streaming` = True. Temperature
  controls sampling randomness — 0 is near-deterministic most-likely-token
  output, which is what you want for "report what the document says" rather
  than creative variation (→ 00 §1).

**LangSmith tracing (lines 95–97)** — `langchain_tracing_v2` (False), API key,
project name.

**AI settings allow-list (lines 99–101)**
- `ai_model_allow_list` = `["gpt-4o-mini", "gpt-4o", "qwen2.5:7b-instruct"]`. The
  *vetted* set of models a workspace admin may select — never free text. The
  comment says "extend deliberately," and the `AiConfigPatch._model_vetted`
  validator enforces it. This exists because an unvetted model could have a
  different (or no) context window, different cost, or weaker instruction-
  following — none of which the rest of the pipeline (prompt sizing, latency
  budget) is built to tolerate.

### Env mechanics of pydantic-settings — lines 103–105
`model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",
extra="ignore")`. Three things to know:
- Every field is populated from an environment variable named after it,
  case-insensitively (`OPENAI_MODEL`, `MILVUS_HOST`, `USE_HYDE`, …). Env beats the
  in-code default.
- `.env` is read as a fallback source when the var isn't already in the real
  environment.
- `extra="ignore"` means unknown env vars are silently dropped — no crash if the
  environment has extra keys. (Contrast with `AiConfigPatch`'s `extra="forbid"`,
  which is the opposite choice for a different reason — see below.)
- Types are coerced from strings: `"true"`/`"false"` → bool, `"10"` → int,
  `"0.76"` → float. This coercion is exactly what the `_clean` "store the coerced
  value" rule (below) leans on.

### `global_rag_config = RagConfig()` — line 123
Constructed **once at import time**, so the env is read once per process and the
same object is shared everywhere. This is the layer-1 base that
`resolve_ai_config` copies from.

**Singleton semantics / gotcha:** because it's a module-level instance, importing
`config` reads the environment *at that moment*. If the environment changes after
import (unlikely in prod, common in tests), the singleton is stale. Overrides do
**not** mutate it — `resolve_ai_config` uses `model_copy(update=...)` to produce a
*new* config, leaving `global_rag_config` untouched. That immutability is why the
`config=` seam is safe to pass around.

### Owner self-test — RagConfig
1. **How does `USE_HYDE=false` in the environment reach the code?**
   pydantic-settings reads the env var matching the field name, coerces `"false"`
   → `False`, and sets `RagConfig.use_hyde` at construction of `global_rag_config`.
2. **Why is `rerank_fetch_k` (50) larger than `retrieval_top_k` (10)?** So the
   dense stage fetches a wide candidate pool the cross-encoder can re-rank and
   promote from; a wider fetch is what turns reranking into a recall gain.
3. **Can an admin set the model to any string?** No — only values in
   `ai_model_allow_list`; the `AiConfigPatch` model validator rejects anything else.
4. **Does an override mutate `global_rag_config`?** No. `resolve_ai_config`
   returns a `model_copy`; the singleton is never mutated.

---

## `src/rag/ai_settings.py`

**Job in one sentence:** store whitelisted per-workspace/per-channel overrides in
one table and resolve them into a real `RagConfig`, defensively re-validating on
read so a poisoned row can never reach the running config.

**Read it in this order:** `OVERRIDABLE` (the whitelist), `AiSettings` (the table +
the partial unique index), `AiConfigPatch` (the write-side schema), `_clean` (the
read-side defense), then `resolve_ai_config` (the merge + provenance).

### `OVERRIDABLE` — lines 26–32
A tuple of exactly the config keys an override may touch: the retrieval toggles and
counts, chat recall knobs, `llm_temperature`, and `openai_model`. This tuple is the
*canonical whitelist* referenced in four places: `_clean` (drop non-whitelisted
keys), `resolve_ai_config` (build provenance), `RagTrace.effective_config`
(rag_chain.py), and the settings router's `_view` (the "effective" projection).

**Gotcha:** to expose a new tunable to admins you must add it to `OVERRIDABLE`
**and** add a validated field to `AiConfigPatch`. Miss either and it's silently
non-overridable or silently unvalidated.

### `AiSettings` table — lines 35–52
- `__tablename__ = "ai_settings"`.
- Columns: `id` (uuid7 PK), `workspace_id` (FK, cascade delete, indexed),
  `channel_id` (nullable FK, cascade delete), `overrides` (JSONB, default `{}`),
  `updated_at` (timezone-aware, `func.now()` on insert and update).
- One row per scope: a workspace-default row has `channel_id IS NULL`; a channel
  override row has a real `channel_id`.

**The two table constraints (lines 37–43) and the partial-index subtlety:**
- `UniqueConstraint("workspace_id", "channel_id", name="uq_ai_settings_scope")`
  (line 38) — one row per (workspace, channel) pair.
- `Index("uq_ai_settings_ws_default", "workspace_id", unique=True,
  postgresql_where=channel_id IS NULL)` (lines 41–42) — a **partial** unique index.

**Why the partial index is necessary (the NULL problem):** in Postgres, `NULL` is
*distinct from every other NULL*, so a composite unique constraint on
`(workspace_id, channel_id)` does **not** prevent two workspace-default rows —
`(ws, NULL)` and `(ws, NULL)` are considered different by the unique constraint
because the NULLs don't compare equal. The comment (lines 39–40) says exactly
this. The partial unique index — "unique on `workspace_id` *where* `channel_id IS
NULL`" — is what actually guarantees at most one workspace-default row per
workspace. This is the constraint the router's upsert-race retry (below) depends on
to fire an `IntegrityError`.

### `AiConfigPatch` — lines 55–76
The **write-side** Pydantic schema (the request body of the PATCH endpoints).
- `model_config = ConfigDict(extra="forbid")` (line 57). The docstring's key line:
  **"extra='forbid' IS the blacklist."** Any field not explicitly declared here is
  rejected at parse time — so a caller cannot smuggle in, say,
  `milvus_host` or `openai_api_key`. The whitelist of *editable* keys is exactly
  the set of declared fields, and `extra="forbid"` is what makes that whitelist
  airtight. (Contrast `RagConfig`'s `extra="ignore"`: env is trusted, HTTP bodies
  are not.)
- Every field is `... | None = None` with **bounds** (lines 59–69):
  `retrieval_top_k` (1–50), `rerank_fetch_k` (1–100), `chat_recall_k` (0–10),
  `chat_recall_fetch_k` (1–50), `chat_decay_half_life_hours` (1–8760),
  `chat_recall_overlap_threshold` (0–1), `llm_temperature` (0–2). The bounds stop
  an admin from setting a pathological value (e.g. top_k = 10_000).
- `_model_vetted` validator (lines 71–76): `openai_model`, if set, must be in
  `global_rag_config.ai_model_allow_list`, else `ValueError`. Free-text models are
  rejected.

### `_clean(overrides, workspace_id)` — lines 79–103
The **read-side** defense in depth. Rows are validated on write, but this
re-validates them on *read*. Walk each stored override:
- Skip keys not in `OVERRIDABLE`, and skip `None` values (line 87).
- Re-validate the single key by constructing `AiConfigPatch(**{k: v})`; on
  `ValidationError`, log a warning and drop that key (lines 89–98).
- Store the **coerced** value `getattr(patch, k)`, not the raw `v` (line 102).

**The two security bugs that shaped this function — read these carefully:**

1. **`model_copy(update=...)` does not re-validate.** `resolve_ai_config` builds
   the effective config with `global_rag_config.model_copy(update=merged)`.
   Pydantic's `model_copy(update=...)` writes the values in *without running any
   validators*. So if a stored row held a wrong type, an out-of-bounds number, or a
   model that has since been *removed from the allow-list*, it would flow straight
   into a live `RagConfig` unchecked. `_clean` re-runs `AiConfigPatch` validation
   per key precisely so those poisoned/stale rows are dropped before the copy
   (docstring, lines 80–84). This matters because the allow-list can shrink after a
   row was written — a model vetted yesterday may be un-vetted today, and only the
   read-time re-check catches it.

2. **Raw-vs-coerced values.** Milvus/JSONB round-trips can hand you the *string*
   `"9"` or `"false"` back. Since `model_copy(update=...)` skips coercion, storing
   the raw string would land a truthy `"false"` (a non-empty string is truthy!) or
   a string where an int is expected into the config. So `_clean` stores the
   value *after* `AiConfigPatch` coerced it — `int 9`, `bool False` — never the raw
   string (comment, lines 99–101). This is the difference between "reranking off"
   actually meaning off and it silently staying on because `"false"` is truthy.

**Gotcha (documented, lines 90–92):** validation is *per key*. If you ever add a
*cross-field* validator to `AiConfigPatch`, `_clean` would miss it (it validates
one key at a time). The note tells you to validate the whole layer at once in that
case.

### `resolve_ai_config(workspace_id, channel_id, db)` — lines 106–132
The merge. Returns `(effective RagConfig, provenance dict)`.
- One query (lines 112–117) fetches both relevant rows: `channel_id IS NULL` (the
  workspace default) OR `channel_id == channel_id` (this channel's override).
- Sort the rows into `ws_over` and `ch_over`, each passed through `_clean` (lines
  118–124).
- **Provenance** (lines 126–128): start with every `OVERRIDABLE` key marked
  `"global"`, then overwrite keys present in `ws_over` with `"workspace"`, then keys
  in `ch_over` with `"channel"`. The result is a per-key map of *where each
  effective value came from* — this is what the trace and the settings `_view`
  surface so you can see why a value is what it is.
- **Merge + copy** (lines 130–131): `merged = {**ws_over, **ch_over}` (channel wins
  over workspace), and `global_rag_config.model_copy(update=merged)` if there's
  anything to override, else the untouched singleton. The return is a *real*
  `RagConfig`, which is why the docstring (lines 3–7) says the existing `config=`
  seam and `RagTrace.effective_config` "stay honest by construction" — nothing
  downstream has to know overrides exist.

**Gotcha:** the merge is a shallow `{**ws, **ch}`, so a channel override of a key
*replaces* the workspace value for that key; it does not deep-merge. That's the
intended precedence (channel beats workspace beats global).

### Owner self-test — ai_settings
1. **Why can't a composite unique constraint guard the workspace-default row?**
   Postgres treats NULLs as distinct, so `(ws, NULL)` and `(ws, NULL)` are "unequal"
   to a unique constraint. A partial unique index (`unique WHERE channel_id IS
   NULL`) is needed instead.
2. **What is `extra="forbid"` doing on `AiConfigPatch`?** Rejecting any field not
   in the whitelist at parse time — it *is* the blacklist, blocking attempts to set
   non-overridable config like `milvus_host` or the API key.
3. **Rows are validated on write. Why re-validate in `_clean` on read?** Because
   `model_copy(update=...)` skips validation, and the allow-list can shrink or a
   row can be corrupted; re-validating per key stops a stale/poisoned value from
   reaching the live config.
4. **Why store the coerced value, not the raw one?** JSONB can return `"false"`/`"9"`
   as strings; `model_copy` won't coerce them, and `"false"` is truthy — storing
   the coerced `False`/`9` is the only way an override actually takes effect.
5. **A key is set at both workspace and channel level. Which wins, and how do you
   tell?** Channel wins (`{**ws_over, **ch_over}`); `provenance[key] == "channel"`
   tells you so.

---

## `src/rag/settings_router.py`

**Job in one sentence:** the HTTP surface for reading and editing the override
layers — GET returns the resolved effective config + raw overrides + provenance,
PATCH validates against `AiConfigPatch` and upserts, with a race-safe retry.

**Read it in this order:** the helpers `_view` and `_apply_patch` (which the
endpoints delegate to), then `_channel_workspace`, then the four endpoints.

### `_view(workspace_id, channel_id)` — lines 22–38
Builds the read response for a scope. Opens a **local** `SessionLocal`, calls
`resolve_ai_config` for the effective config + provenance, fetches the scope's raw
`AiSettings` row (matching `channel_id IS NULL` for the workspace scope), and
returns a dict with three keys:
- `effective`: `{k: getattr(cfg, k) for k in OVERRIDABLE}` — the resolved values.
- `overrides`: the raw stored dict (or `{}` if no row).
- `provenance`: the per-key origin map.

**The deliberate local `SessionLocal` import (lines 24–26):** the comment says it
outright — *"local import by design: tests monkeypatch `database.SessionLocal`
(race test seam)."* Importing `SessionLocal` at module top would bind the name at
import time, and a test's monkeypatch of `database.SessionLocal` afterward wouldn't
be seen. Importing it *inside* the function re-reads `database.SessionLocal` on
every call, so the test double is honoured. `_apply_patch` does the same (line 42).
This is what lets the race test below actually inject a concurrent writer.

### `_apply_patch(workspace_id, channel_id, patch)` — lines 41–76
The write path — an upsert with null-clear semantics and a race retry.
- `delta = patch.model_dump(exclude_unset=True)` (line 43). **Null-clear
  semantics:** `exclude_unset=True` means only fields the client *actually sent*
  appear in `delta`. A field sent as `null` is present with value `None` — and
  `_merge_into` treats `None` as "remove this key" (`merged.pop(k, None)`, line
  49). So `{"use_hyde": null}` *clears* the override (reverting to the inherited
  value); a field simply omitted is left untouched. That distinction only works
  because `exclude_unset` separates "sent null" from "not sent."
- `_merge_into(overrides)` (lines 45–52): copy the existing overrides, then for
  each `delta` key either pop it (value None) or set it.
- `_scope_row(db)` (lines 54–59): select the row for this exact scope.
- Upsert body (lines 61–76): select the row; if absent, create a new `AiSettings`
  with empty overrides and add it; set `row.overrides = _merge_into(...)`; commit.

**The IntegrityError upsert-race retry (lines 67–76) — the race it closes:** two
requests can PATCH the *same* previously-nonexistent scope concurrently. Both run
`_scope_row`, both see `None`, both build a new `AiSettings` and try to insert.
This is a check-then-insert (TOCTOU) race. The **partial unique index** (or the
composite unique constraint) fires on the second commit, raising `IntegrityError`.
The `except` (lines 69–76) rolls back, re-selects the row (which the winning
request has now committed, so it exists), merges the delta into *that* row, and
commits once more. One retry is sufficient because after the rollback the row is
guaranteed to exist — the second attempt is a plain update, not an insert, so it
can't collide again.

**Why this matters:** without the retry, the losing concurrent first-PATCH would
500 on an integrity violation. The retry turns the race into a correct, serialized
merge. It is the exact reason the partial unique index in `ai_settings.py` must
exist — the constraint is what *signals* the race so the code can recover.

**Gotcha:** the retry assumes the `IntegrityError` came from the scope-uniqueness
collision. If you add other constraints to `ai_settings` that can also raise
`IntegrityError` here, the blanket `except IntegrityError` would mis-handle them —
narrow it if that ever happens.

### `_channel_workspace(channel_id)` — lines 90–95
Async helper: resolve a channel's `workspace_id`, or `404` if the channel doesn't
exist. Used by both channel endpoints so a channel override is always resolved
against its real parent workspace.

### The four endpoints — lines 79–108
- `GET /ai/config` workspace (lines 79–81), guard `require("workspace:view")` →
  `_view(workspace_id, None)`.
- `PATCH /ai/config` workspace (lines 84–87), guard
  `require("workspace.role:manage")` → `_apply_patch(...)` then return the fresh
  `_view`.
- `GET /ai/config` channel (lines 98–101), guard `require("channel:view")` →
  resolve workspace, `_view(ws, channel_id)`.
- `PATCH /ai/config` channel (lines 104–108), guard
  `require("workspace.role:manage")` → resolve workspace, `_apply_patch`, return
  fresh `_view`.

**The guard asymmetry to notice:** *viewing* config takes the ordinary
view perm (`workspace:view` / `channel:view`), but *editing* — even a channel's
config — requires the workspace-level `workspace.role:manage`. A mere channel
member cannot retune the AI; only a workspace manager can. Both PATCH endpoints
re-return the resolved view so the client immediately sees the merged effect
(including provenance) of its write.

### Owner self-test — settings_router
1. **How does a client *clear* an override versus leave it alone?** Send the field
   as `null` to clear it (`exclude_unset` keeps it in `delta` as `None`, and
   `_merge_into` pops it); omit the field entirely to leave it untouched.
2. **Why are `SessionLocal` imports done inside the functions, not at module top?**
   So tests can monkeypatch `database.SessionLocal` and have the router pick up the
   double on the next call — the race-test seam.
3. **What race does the `except IntegrityError` retry close, and what makes it
   safe?** Two concurrent first-PATCHes both insert the same new scope row; the
   unique index rejects the second. After rollback the row exists, so the single
   retry is a plain update that can't collide again.
4. **Who can edit a channel's AI config?** Only a workspace manager
   (`workspace.role:manage`) — not an ordinary channel member, even for a channel-
   scoped override.
5. **What three things does a GET return, and where does each come from?**
   `effective` (from `resolve_ai_config`'s copied config), `overrides` (the raw
   stored JSONB row), and `provenance` (per-key origin from `resolve_ai_config`).
