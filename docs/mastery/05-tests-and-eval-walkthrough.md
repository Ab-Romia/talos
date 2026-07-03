# 05 — Tests and Eval Walkthrough

Two separate worlds live under test-shaped directories here: `tests/` is a
real pytest suite that boots the actual FastAPI app against a real Postgres
test database (no mocking of the ORM, no in-memory DB substitution), and
`tests/rag_evaluation/` is an offline LLM-judged evaluation harness meant to
be driven from a notebook, not from `pytest -q`. You need to be fluent in
both, and in exactly where the line between them is.

---

## 1. Test architecture

### How `tests/conftest.py` boots the app

**The `init` fixture** (`tests/conftest.py:23-30`), `scope="session"`,
`autouse=True`:
```python
@pytest.fixture(scope="session", autouse=True)
async def init():
    from app import lifespan
    from database import engine, Base
    Base.metadata.drop_all(engine)
    async with lifespan(app):
        yield
```
Runs once for the entire test session, before any test. **`drop_all` then
`lifespan(app)`** — the drop happens *first*, unconditionally, against
whatever the test DB currently looks like; the app's own `lifespan` context
manager (defined in `app.py`, not shown here) is what actually runs
`Base.metadata.create_all(engine)` per this repo's "no Alembic" convention.
So the semantics are: **every test run starts from a genuinely empty schema,
rebuilt from the current SQLAlchemy models** — there is no reliance on
migrations being up to date, and no leftover state from a previous test run
(or a previous branch's schema) can linger. This is also why tests require a
real Postgres reachable at the configured test DB URL — `drop_all`/
`create_all` need a real database engine, not a mock.

**`db_session`** (33–46), `autouse=True`, function-scoped: opens a fresh
`SessionLocal()` for *every single test*, and overrides the FastAPI
dependency `_get_db` (`app.dependency_overrides[_get_db] = lambda: db`) so
that HTTP requests made through the `client` fixture during that test use
this exact same session object — meaning a test can write via `db_session`
and immediately assert on it via an HTTP response (or vice versa) without a
transaction-visibility mismatch. Rolls back on exception, always pops the
override in `finally` so it doesn't leak into the next test.

**Gotcha you must internalize**: this is **not** a rollback-per-test
transaction wrapper (the common pytest-django-style pattern). Fixtures like
`test_workspace` and `test_users` explicitly `db_session.delete(...)` +
`db_session.commit()` in their own teardown — because nothing else will undo
their `commit()` calls. If you add a fixture that creates rows and forget
explicit teardown, those rows persist in the test Postgres database across
tests (and across runs, until the next `drop_all`). Follow the existing
teardown pattern (rollback first in case a prior assertion left the session
dirty, then delete + commit, wrapped in try/except that rolls back and
re-raises on failure) for anything you add.

**`client`** (49–51): a single `session`-scoped `TestClient(app)` — shared
across the whole run, not recreated per test.

**`path`** (54–61): a small helper fixture that resolves a route by name (or
by passing the view function itself, using `route.__name__`) via FastAPI's
`url_path_for`, so tests don't hardcode URL strings that could drift from the
router definitions:
```python
def build_path(route: str | Callable, **path_params):
    if callable(route):
        route = route.__name__
    return client.app.url_path_for(route, **path_params)
```
Used like `path(ask_question, channel_id=...)` in `test_ask_endpoint.py`.

**`test_channel` / `test_user` / `auth_token`**: layered factory fixtures —
`test_user` pulls one user off the `test_users` generator fixture (itself
building fake users via Faker and committing them); `test_workspace` creates
a `Workspace` owned by `test_user` plus a `Role` with baseline view
permissions; `make_channel`/`test_channel` create a `Channel` inside that
workspace; `test_session`/`auth_token` build a real signed JWT
(`create_token(SessionClaims(...))`) against a real `UserSession` row, so
authenticated endpoint tests exercise the actual auth dependency chain
(`active_user` → JWT decode → session lookup), not a mocked-out auth layer.

### `IS_TEST=1` mechanics

Two independent places consume it:
- `src/config/config_.py`: `is_pytest() -> "IS_TEST" in os.environ` (checks
  *presence*, any value — even `IS_TEST=0` counts as "set"), and
  `Config.is_test: bool = False` as a settings field that gets populated from
  the actual env var value through pydantic-settings' normal env-loading (so
  here the *value* matters, not just presence — pydantic parses `"True"`/
  `"1"` etc. as boolean `True`).
- `pyproject.toml`'s `[tool.pytest.ini_options]` sets `env = ["IS_TEST=True"]`
  via the `pytest-env` plugin — this injects the env var **before test
  collection**, which matters because `broker.py` reads `cfg().is_test` at
  **import time** to decide whether to swap in `InMemoryBroker` (see the
  background-pipelines chapter §4). If `IS_TEST` were set by a fixture
  instead, it would run too late — any module already imported (including
  `broker.py`, imported transitively by `app.py`) would have already bound to
  the real Redis-backed broker.

Practically: you rarely need to pass `IS_TEST=1` by hand on the command line
because `pytest-env` sets it automatically once pytest starts — but plan
docs in this repo consistently prefix commands with `IS_TEST=1` anyway as a
defensive habit (e.g. for direct `python -c` invocations or scripts that
import `broker`/`config` outside of a pytest run, where nothing else would
set it).

### Why `uv run python -m pytest`, not bare `pytest`

Documented directly in the plan files under `docs/superpowers/plans/`: a bare
`uv run pytest` (or a bare global `pytest`) can resolve to a **stale global
pytest binary** on the machine rather than the one pinned in this project's
`uv`-managed `.venv` — which may be missing project dependencies, be the
wrong Python version, or simply not have `pythonpath = ["src", "."]" wired
in the way this project's `pyproject.toml` configures it (though that config
lives in `pyproject.toml` and would apply either way *if* the right pytest
binary is used — the actual risk is dependency/interpreter mismatch, not the
ini options). `uv run python -m pytest` forces Python to resolve `pytest` as
an installed module inside the exact interpreter `uv` has pinned for this
project (Python 3.13.12 per project memory), guaranteeing you're running
against the same dependency set the project actually declares.

Also requires the test Postgres container running first:
`docker compose up -d postgres-test` (one-time per session, not per test
run) — since `init()` needs a real reachable Postgres.

---

## 2. Directory-by-directory

### `tests/rag/*` — one line per file, what invariant each protects

- **`test_ai_settings_api.py`** — the `/ai-settings` HTTP surface: GET
  returns global defaults when unset, PATCH upserts and is reflected by a
  subsequent GET, PATCH rejects blacklisted/out-of-bounds fields, and a
  concurrent-insert race on first-write is retried correctly rather than
  raising `IntegrityError` to the caller.
- **`test_ai_settings.py`** — the `AiSettings`/`AiConfigPatch` domain logic
  below the HTTP layer: field whitelisting, numeric bounds, model allow-list
  enforcement, layered resolution (global → workspace → channel) with
  provenance tracking, and safe degradation when a stored override is
  type-poisoned or references a model since removed from the allow-list.
- **`test_ask_endpoint.py`** — the `/ask` HTTP surface end-to-end (RAGChain
  monkeypatched so no live Milvus/LLM call happens): streaming + persistence
  of the exchange, a 502 (not 500) on prepare-failure with nothing persisted,
  mid-stream failure marks the stream and persists nothing, debug mode
  appends a trace payload, citation footers are stripped before persisting,
  AI messages broadcast to the channel's realtime room, workspace/channel
  AI-settings overrides actually reach the chain, and the tier-1 tail's char
  budget (`chat_context_char_budget`): a burst of huge un-indexed messages
  injects only what fits newest-first, while a single over-budget message is
  still injected whole (never-empty, never-truncate).
- **`test_build_pipeline.py`** — `build_rag_pipeline` is the single shared
  retrieval composition used everywhere; specifically proves two historical
  "toggle lies" are fixed: reranking widens the candidate pool (fetches
  `rerank_fetch_k`, returns `retrieval_top_k`) rather than reranking within
  the same top-k, and enabling hybrid retrieval can no longer silently no-op
  when a corpus isn't supplied.
- **`test_chat_recall_dedupe.py`** — a chat segment that's already in the
  directly-injected recency tail (message briefly present in both the
  un-indexed tail and, once committed, Milvus) must not be double-counted in
  context — `RAGChain` drops tail `message_ids` from tier-2 (vector) recall,
  and gracefully degrades to file-only context if chat selection itself
  fails.
- **`test_chat_selection.py`** — pure unit tests of the chat re-ranking
  function `select_chat_context`: recency beats slightly-more-relevant-but-
  ancient results, a lone old candidate still survives if it's the only one,
  near-duplicate segments get suppressed, and the `k` cap plus missing
  `sent_at` metadata are handled without crashing.
- **`test_chunking.py`** — chunking hygiene for `build_chunk_documents`:
  `by_title` drops `Header`/`Footer` noise elements, merges short fragments
  while retaining section metadata, respects `max_characters`, honors the
  `chunk_prepend_section_title` flag, and — critically — the `"recursive"`
  legacy strategy's output is byte-identical to its pre-refactor behavior
  (the reproduction-baseline guarantee).
- **`test_collection_unified.py`** — there is exactly **one** Milvus
  collection (`WORKSPACE_COLLECTION == "talos_documents" ==
  global_rag_config.milvus_collection_name`); asserts the old split
  (a config default of `documents_v2` vs. a separately hardcoded
  `talos_documents` used elsewhere) is gone for good.
- **`test_config_seam.py`** — `RagConfig` is a real, honored, injected
  dependency in every factory that claims to take one (`get_llm`,
  `get_embeddings`, HyDE construction) — not a decorative parameter silently
  ignored in favor of the `global_rag_config` singleton; also checks the
  embeddings cache is correctly keyed per-model (not one global cache
  regardless of requested model).
- **`test_embeddings_selection.py`** — the HuggingFace embedder branch of
  `get_embeddings`/`_build_embeddings` honors `config.embedding_model` (not
  hardcoded), and BGE-family models automatically get the BGE query
  instruction prefix; an unknown embedding provider still raises rather than
  silently falling back.
- **`test_eval_uses_production_path.py`** — "eval == ship": the eval harness
  (`tests/rag_evaluation/eval_utils.py`) must not contain a private
  reimplementation of retrieval — it must import and drive the real
  `build_rag_pipeline`/`RAG_PROMPT` — and its `production_default` ablation
  row must be *derived from*, not hand-copied from, the live
  `global_rag_config`, so it can never silently drift out of sync with what
  actually ships.
- **`test_message_text.py`** — `message_text()` is the single seam
  converting `Message.content` (either a plain string or a ProseMirror
  JSONB rich-text doc) into plain text; None content becomes `""`, plain
  strings pass through, ProseMirror docs get their text nodes extracted.
- **`test_rag_chain.py`** — `RAGChain` built on the shared pipeline via
  dependency injection (fake retriever/llm, no live services touched): the
  live question is never duplicated into `chat_history`, a structured
  `RagTrace` is populated after every query, `prepare()` then
  `stream_answer()` produces output identical to the older combined
  `stream_query()` wrapper, `prepare()` propagates a retriever failure
  instead of swallowing it, and trace records timing plus a request id
  (both auto-generated and explicitly passed in via constructor).
- **`test_trace.py`** — `RagTrace` (the structured "what did this RAG run
  actually use" record shared by `/ask` debug mode, `debug_ask.py`, and the
  eval harness) round-trips through `as_dict()`, has safe defaults when
  unpopulated, and `doc_summary` correctly extracts metadata + a text snippet
  from a `Document`.

### `tests/chat/test_chat_indexing.py`

Covered in depth in the background-pipelines chapter (§1), but as a test-
suite summary: `TestBuildChatDocuments` (one doc per short message, long
messages split with consistent `message_ids`/`chunk_index`, role prefix
reads the `role` column correctly including the `MessageRole` enum case);
`TestIndexPendingMessages::test_indexes_settled_skips_fresh_and_is_idempotent`
(the core end-to-end behavior — old message indexed, fresh message skipped,
a second run is a true no-op); `test_indexer_skips_tick_when_lock_held` and
`test_indexer_releases_lock_after_successful_run` (the two advisory-lock
invariants — see below); `test_tick_drains_multiple_batches` (the
`chat_tasks.py` drain loop); `TestBuildChatSegments` (boundary logic:
inactivity gap, `max_messages` cap, never mixing channels);
`TestSegmentDocuments::test_segment_document_metadata` (the full metadata
contract on a real multi-message segment).

**The lock-held test using a second real connection**
(`test_indexer_skips_tick_when_lock_held`, lines 86–113): opens its **own**
`SessionLocal()` (named `other`), takes the advisory lock on it directly via
raw SQL (`pg_try_advisory_lock`), and *while still holding it*, calls
`index_pending_messages(...)` from the main test flow. This proves the lock
genuinely blocks a *second, independent, real* database connection — not
just a re-entrant call on the same connection (which Postgres session
advisory locks would trivially allow, since re-acquiring the same lock on
the same connection is a no-op success, not a contention case). This is the
only way to actually exercise the concurrent-run scenario the lock exists
for.

`test_indexer_releases_lock_after_successful_run` (116–144) is the direct
regression test for the connection-affinity leak documented in
`chat_indexing.py`: it runs a real successful indexing pass, then opens a
**third, fresh** `SessionLocal()` and asserts the lock is *immediately*
acquirable. If the unlock had ever hit the wrong pooled connection (the bug
class the dedicated `lock_conn` prevents), this test would hang or fail here
— every subsequent run of the indexer test suite would then also fail with
"lock held elsewhere", since the leak persists for the lifetime of the
underlying connection.

### `tests/processing/test_process_file.py`

Two tests, both driving `tasks.process_file.original_func(...)` directly
(bypassing the broker entirely — see the background-pipelines chapter §6 for
why `.original_func` is the right tool for exercising a task without a
worker):

- `test_process_file_stamps_indexed_on_success` — claims the file, calls
  the (faked) document processor, stamps `INDEXED`.
- `test_process_file_stamps_failed_on_error` — the faked processor raises;
  asserts the row ends up `PROCESSING_FAILED` and the exception is
  re-raised out of `process_file` (not swallowed).

**Monkeypatch targets vs. import sites — the pattern to copy**:
```python
monkeypatch.setattr(tasks, "MinIOFileSystem", _FakeStorage)
monkeypatch.setattr("processing.documents.process_document", _fake_process_document)
```
`MinIOFileSystem` is imported at the **top** of `processing/tasks.py`
(`from filesystem.storage.minio import MinIOFileSystem`), so patching it
requires patching the **name bound inside `tasks`'s own module namespace**
(`tasks.MinIOFileSystem`) — patching
`filesystem.storage.minio.MinIOFileSystem` instead would have no effect,
because `tasks.py` already holds its own reference to the original class by
the time the test runs. `process_document`, by contrast, is imported
**inline inside the function body** of `process_file`
(`from processing.documents import process_document` at call time, not at
module load) — so there is no `tasks.process_document` name to patch at all;
you must patch it at its **origin** module path,
`"processing.documents.process_document"`, using the string form of
`monkeypatch.setattr` (which resolves the dotted path itself), because the
lookup that matters happens fresh at call time inside `process_file`, after
the patch has already taken effect. **The general rule**: if a module does
`from x import y` at the top, patch `module.y`; if it does the import inside
a function body (or otherwise references `x.y` dynamically at call time),
you must patch `x.y` directly. Getting this backwards is the single most
common way a "passing" test is silently not testing what you think it is
(the real `MinIOFileSystem`/`process_document` still runs, and the test
happens to still pass, or worse, hits real Milvus/MinIO).

The `_FakeStorage.__init__` signature (`config, workspace_id, channel_id=None`)
matches `MinIOFileSystem`'s real constructor signature exactly — the test
then asserts `_FakeStorage.last.workspace_id`/`channel_id` match the file
record, which is how `test_process_file_stamps_indexed_on_success` verifies
the per-file, workspace-scoped construction pattern from the background-
pipelines chapter §3 without touching real MinIO.

---

## 3. The eval harness — `tests/rag_evaluation/eval_utils.py`

### What it is, and what it explicitly is not

This is **not** part of the pytest suite (no `test_` functions live in this
file itself — `tests/rag/test_eval_uses_production_path.py` tests *about*
this file by reading its source as text, not by importing and running it as
pytest tests). It's a library of helpers meant to be imported from a Jupyter
notebook (`evaluation/rag_evaluation.ipynb` / `rag_evaluation_talos.ipynb`)
that drives real LLM calls and (optionally) real embeddings, costs real
money per run, and produces a judged report — categorically different from
the fast, hermetic, DB-backed pytest suite above.

### `RagVariant` → production `build_rag_pipeline` (261–281, 402–541)

`build_retriever` (261–281) is explicitly "a thin adapter over the
PRODUCTION `build_rag_pipeline`" — it builds a `RagConfig` from the sweep's
flags (`top_k`, `use_hybrid`, `use_rerank`) and calls the exact same
`rag.retrieval.retrievers.build_rag_pipeline` the live app uses. `RagVariant`
(402–541) goes further: its constructor builds the vectorstore (optionally
with HyDE query embeddings via `_hyde_embeddings`, which itself constructs
`HypotheticalDocumentEmbedder.from_llm` the same way production's
`get_hyde_embeddings` does, just with injected models so the notebook
controls which LLM/embeddings are used), then calls the real
`build_rag_pipeline(config.to_rag_config(), vectorstore, corpus=chunks)` to
get `self.retriever` — this is the same production retriever composition
(dense/hybrid → rerank-with-candidate-widening → compression) exercised in
`test_build_pipeline.py`, just run against an in-memory vectorstore built
from the eval's own corpus instead of live Milvus. `answer()` (481–524) then
runs the real production `RAG_PROMPT` from `config.py` against the retrieved
context — a **closed-book** variant swaps in a separate plain prompt
(467–477) specifically so a no-retrieval baseline isn't unfairly primed with
"use the following context" language when there is no context.

### `VariantConfig` → `RagConfig` (305–329)

```python
def to_rag_config(self):
    from config import RagConfig, CompressionType
    return RagConfig(
        use_query_rewrite=self.use_rewrite,
        use_hyde=self.use_hyde,
        use_reranking=self.use_rerank,
        use_hybrid_retrieval=self.use_hybrid,
        compression_type=CompressionType(self.compression),
        compression_similarity_threshold=self.compression_threshold,
        retrieval_top_k=self.top_k,
    )
```
Every ablation row is a `VariantConfig` dataclass that maps 1:1 onto the
real `RagConfig` fields the production pipeline reads — there is no separate
"eval config" schema with its own independent meaning; this is exactly what
`test_eval_uses_production_path.py::test_variant_config_maps_to_rag_config`
locks down.

### The ablation grid (`default_variants`, 332–399)

Rows, in order: `closed_book` (no retrieval at all — pure LLM knowledge
baseline), `dense_only` (bare dense retrieval, nothing else on),
**`production_default`** (see below), `+rewrite`, `+hyde` (rewrite + HyDE),
`+rerank` (rewrite + HyDE + rerank), `hybrid+rerank` (adds hybrid retrieval
on top), `compression_calibrated` (everything on, but the embeddings
compression-filter similarity threshold lowered from 0.76 → 0.50, testing
whether a prior compression regression was a config-only bug),
`everything_on_stress` (every feature on at the *default* 0.76 threshold —
explicitly named "_stress" to make clear this is a ceiling/stress-test row,
not a recommended or shipped configuration).

**`production_default` is derived, not copied** (349–361):
```python
from config import global_rag_config as _c
VariantConfig(
    name="production_default",
    use_rewrite=_c.use_query_rewrite,
    use_hyde=_c.use_hyde,
    use_rerank=_c.use_reranking,
    use_hybrid=_c.use_hybrid_retrieval,
    compression=_c.compression_type.value,
    top_k=top_k,
)
```
This row reads live values off `global_rag_config` at call time — if
someone flips a production default in `config.py` (e.g. turns HyDE on),
this row automatically reflects the new shipped behavior on the next eval
run, with zero manual synchronization. This is the row
`test_production_default_mirrors_shipped_config` locks down, and it's the
row every eval report should headline, because it's the only row that's
*guaranteed* to represent what a real user actually experiences today.

### Metrics: IR + judge

**IR metrics** (970–1005, unified via `ir_metrics_at_k` at 1387–1405): classic
retrieval metrics computed from `retrieved_ids` vs. `gold_ids` —
`hit_rate_at_k`, `recall_at_k`, `precision_at_k`, `reciprocal_rank`,
`ndcg_at_k`. `ir_metrics_at_k` bundles all five under a `f"{metric}@{k}"`
key naming convention, matching the BEIR benchmark reporting style
(Thakur et al., NeurIPS 2021) — the docstring specifically recommends
reporting both `@5` (matches production `top_k`) and `@10` (BEIR leaderboard
convention) so numbers are externally comparable.

**LLM-as-judge metrics** (1081–1164), all via `_structured_invoke` (uses
OpenAI native Structured Outputs, `method="json_schema", strict=True`, with
exponential-backoff retries — no regex parsing of free-text judge output):
- `judge_faithfulness` — is the answer grounded in the retrieved context?
  Returns `None` (not `0.0`) when there's no context at all (closed-book),
  because faithfulness is *structurally undefined* without context, not
  zero — an important distinction for aggregation, cites Ragas docs +
  arXiv:2504.14891.
- `judge_answer_relevancy` — does the answer address the question (0/0.5/1
  scale)?
- `judge_context_relevance` — per-chunk relevance to the question, mean
  over top-k; also `None` when there are no contexts.
- `judge_correctness` — factual correctness against a reference answer.
- `answer_similarity` (1154–1164) — a non-LLM, purely embedding-cosine
  metric (mirrors Ragas's `semantic_similarity`) between answer and
  reference — cheap, deterministic, useful as a sanity cross-check against
  the LLM judge scores.

Statistical rigor layered on top: `bootstrap_ci` (percentile bootstrap over
resampled means), `paired_wilcoxon` (paired Wilcoxon signed-rank with
rank-biserial effect size, `scipy` if available else a hand-rolled normal
approximation), `holm_bonferroni` (step-down p-value correction across
multiple comparisons), and `two_judge_consistency` (re-judges a sample with
a second LLM to bound self-enhancement / judge bias, per Zheng et al.,
NeurIPS 2023 §4 — Pearson + Spearman correlation + mean absolute
disagreement between two judges).

### How to run it

This is **not** run via `pytest`. It's driven from
`evaluation/rag_evaluation.ipynb` (Wikipedia-CS corpus) or
`rag_evaluation_talos.ipynb` (real Talos-representative docs, loaded via
`load_local_corpus`) — see also `evaluation/live_pdf_eval/` for a scripted,
non-notebook runner variant (`REPORT.md` there documents a specific run).
Typical flow inside the notebook:
1. `load_corpus(...)` or `load_local_corpus(...)` → `chunk_documents(...)`.
2. Build embeddings + vectorstore once (`build_vectorstore`).
3. `synthesize_qa(...)` (LLM-generated single-hop + multi-hop Q&A, second-
   pass filtered by `review_qa`) — or `load_hotpotqa_intersected(...)` for a
   human-authored multi-hop benchmark intersected with your corpus by
   article title.
4. For each `VariantConfig` in `default_variants()`, build a `RagVariant`
   and call `.answer(question)` per test item, with a `JsonCache` (1254–1280)
   wrapping the LLM calls so re-running the notebook doesn't re-bill OpenAI
   for unchanged (variant, question) pairs — cache key is a SHA-256 of the
   variant's config dict + the question text.
5. Score with the IR metrics (retrieval-only) and judge metrics (full
   answer quality), aggregate with bootstrap CIs, compare variants pairwise
   with `paired_wilcoxon` + `holm_bonferroni`.

`env_check()` (1295–1301) is the notebook's first-cell sanity check — verifies
`OPENAI_API_KEY` is set, `src/` is on `sys.path` (the module does this itself
at import time, lines 39–44, by walking up from its own file location — so
this check is mostly a double-confirmation), and the default corpus pickle
exists on disk.

### The two honest parity gaps

1. **Hybrid retrieval is eval-only-exercised in one specific sense**: the
   ablation grid *does* include `hybrid+rerank` and drives it through the
   real `build_rag_pipeline`, so hybrid retrieval logic itself is genuinely
   exercised end-to-end with real corpus data — this is not a fake. The gap
   is narrower: hybrid retrieval requires an in-memory BM25 corpus
   (`EnsembleRetriever` combining dense + `BM25Retriever`), and the eval
   harness constructs that corpus itself from its own loaded chunks
   (`corpus=chunks` passed into `build_rag_pipeline`) — the *production*
   code path (`process_document`/`RAGChain` in the live app) does not
   currently build or pass an equivalent in-memory BM25 corpus at query
   time, so hybrid retrieval, while implemented and unit-tested
   (`test_build_pipeline.py::test_hybrid_with_corpus_builds_ensemble` /
   `test_hybrid_without_corpus_warns_and_falls_back`), is validated for
   *retrieval quality* only inside the eval harness's synthetic-corpus
   setup, not against what a live user's workspace actually does — check
   `use_hybrid_retrieval`'s live default and whether the app's real query
   path supplies a `corpus` before trusting eval hybrid numbers as
   representative of production hybrid behavior.
2. **The two-tier chat recall system (recency tail + Milvus-indexed chat
   history) is entirely unevaluated by this harness.** `default_variants()`
   and every `RagVariant` in this file only ever construct a retriever over
   file-document chunks (`source="chat"` chat segments, `chat_selection.py`'s
   re-ranking, and the tail-dedupe logic in `RAGChain` are all covered by
   *unit* tests — `test_chat_selection.py`, `test_chat_recall_dedupe.py` —
   but never by this judged, corpus-scale eval harness). If you're asked
   "how good is chat memory retrieval quality," the honest answer today is
   "unit-tested for correctness of the mechanism, not quality-evaluated at
   scale" — there is no judged benchmark analogous to the file-document
   ablation grid for chat recall.

---

## 4. How to add a test for each kind of change

### New config knob (a new `RagConfig` field)

1. Add the field to `RagConfig` in `config.py` with a sensible default that
   preserves current behavior when unset (config changes must not flip
   production behavior by accident).
2. Add/extend a `tests/rag/test_config_seam.py`-style test proving the field
   is actually *read* by whichever factory function claims to use it — don't
   just test the config object parses; prove the seam is real:
```python
def test_new_knob_is_honored():
    cfg = RagConfig(my_new_flag=True)
    result = the_relevant_factory(config=cfg)
    assert <observable difference caused by my_new_flag>
    # and prove the default config path is unaffected:
    default_result = the_relevant_factory()
    assert default_result != result  # or however "off" looks
```
3. If the field affects the ablation grid, extend `VariantConfig` +
   `to_rag_config()` in `eval_utils.py` and re-run
   `test_eval_uses_production_path.py` to confirm the mapping test still
   passes (it enumerates the fields — check whether it needs updating too).

### New retrieval stage (e.g. a new reranking or filtering step)

1. Write a **pure unit test** first, following `test_chat_selection.py`'s
   pattern: construct `Document` objects with just the metadata your stage
   reads, call the stage function directly, assert on ordering/filtering —
   no Milvus, no LLM, no DB.
2. Wire it into `build_rag_pipeline` (`rag/retrieval/retrievers.py`), gated
   by a config flag defaulting to off/current-behavior, mirroring how
   `use_reranking`/`use_hybrid_retrieval` are gated.
3. Extend `test_build_pipeline.py` with a test proving the new stage
   composes correctly with the existing pipeline (e.g. "reranking still
   widens then narrows even with the new stage in between" — check for
   exactly the kind of "toggle lie" bug that file's existing tests guard
   against: does turning the flag off truly restore prior behavior byte for
   byte?).
4. Optionally extend the eval harness's `VariantConfig`/`default_variants()`
   with a new ablation row so the new stage gets judged, not just unit
   tested — remember §3's parity-gap lesson: a stage that's only in the
   ablation grid but never wired into the live query path (like hybrid's
   corpus gap) is a trap waiting to be documented as a third parity gap.

### New endpoint

1. Add fixtures as needed reusing `tests/conftest.py`'s existing factories
   (`test_channel`, `auth_token`, `path`) — don't rebuild auth/workspace
   scaffolding per test file.
2. Follow `test_ask_endpoint.py`'s shape: monkeypatch the heavy dependency
   (RAGChain, or whatever service the endpoint calls) so the test never
   touches Milvus/OpenAI/MinIO, use `client.post(path(my_endpoint, ...), ...)`
   with `_h(auth_token)` headers, and assert both the HTTP response shape
   *and* the resulting DB state via `db_session` directly (not by re-fetching
   through another endpoint that might have its own bugs — see the
   `test_ask_endpoint.py` docstring's explicit rationale for reading
   persistence via direct DB query instead of `GET /messages`).
3. Cover the unhappy paths explicitly: a dependency failure before any
   streaming/side-effect starts should degrade cleanly (502, not 500) and
   persist nothing; a failure mid-stream should mark the stream as failed
   and also persist nothing partial — mirror
   `test_ask_prepare_failure_is_502_and_persists_nothing` /
   `test_ask_midstream_failure_marks_stream_and_persists_nothing`.
4. Run just the new file first (`IS_TEST=1 uv run python -m pytest
   tests/rag/test_my_new_endpoint.py -q`), then the full relevant directory
   gate before considering it done (`tests/rag tests/chat` at minimum, add
   `tests/processing` if you touched anything in that pipeline).

### Background-task-shaped change (cron task, taskiq task)

Reuse the `test_process_file.py` / `test_chat_indexing.py` pattern directly:
call `.original_func(...)` to bypass the broker, monkeypatch heavy externals
at their correct target (module-top-level import → patch the caller's bound
name; function-body-local import → patch the origin module's attribute, per
§2's monkeypatch rule), and if the task touches shared mutable state that a
concurrent second run could corrupt, write the "second real connection/
session holds a lock or state, first run must observe and defer" style test
demonstrated by `test_indexer_skips_tick_when_lock_held`.

### Self-test

**Q: Why does `test_ask_endpoint.py` assert persisted messages via
`db_session` directly instead of via `GET /messages`?**
A: `GET /messages` currently 500s on any assistant-role row (a pre-existing
bug: `MessageSchema.sender_id` is non-optional but assistant rows have
`sender_id NULL`) — using the direct DB read avoids coupling the `/ask` test
suite to an unrelated, already-known bug in a different endpoint.

**Q: You wrote a test that patches `tasks.SomeClient` but the real client
still gets constructed when you run the test. What's the most likely
cause?**
A: The import site is wrong — either the target module imports the class
inline inside the function body (patch the origin module's attribute
instead of the caller's name), or you patched the origin module while the
caller imported it at top-level (patch the caller's bound name instead).
Check where the `import` statement for that name actually lives relative to
where it's used.

**Q: Why do `test_workspace`/`test_users` explicitly delete-and-commit in
their fixture teardown instead of relying on the test session rolling
back?**
A: `tests/conftest.py` does not wrap tests in a rollback-only transaction —
`db_session` fixtures `commit()` freely, and only the session-scoped `init`
fixture's `drop_all` at the very start of the whole run resets the schema.
Anything committed during a test persists in the real test Postgres unless
its fixture explicitly tears it down.

**Q: Can you trust the eval harness's `hybrid+rerank` row as proof that
hybrid retrieval works well for real Talos users?**
A: Only for the retrieval-quality claim in the eval's own synthetic-corpus
setup — the eval harness constructs its own in-memory BM25 corpus and passes
it into the real `build_rag_pipeline`, so the composition logic itself is
genuinely exercised. What's unverified is whether the *live* query path
(the actual `/ask` flow against a user's workspace) supplies an equivalent
corpus at query time — confirm that before treating the eval number as
representative of production behavior.
