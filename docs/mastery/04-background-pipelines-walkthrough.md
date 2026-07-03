# 04 — Background Pipelines Walkthrough

Everything in this chapter runs outside the HTTP request/response cycle: taskiq
tasks executed by a worker process, plus one cron job. You need to be able to
explain, line by line, why each piece of defensive code exists — most of it is
there because of a real bug class (double-processing, connection-affinity
leaks, orphaned locks), not decoration.

---

## 1. `src/processing/chat_indexing.py`

### Job in one sentence
Periodically pull settled (old enough, not-yet-indexed) chat messages out of
Postgres, group them into topic-coherent conversation segments, embed those
segments into the shared Milvus collection tagged `source="chat"`, and stamp
the source rows so they aren't re-indexed.

### Read it in this order
1. Module docstring (lines 1–12) — establishes the schema assumptions this
   file depends on.
2. `INDEXER_LOCK_KEY` (line 36) — the constant that everything else revolves
   around.
3. `build_chat_segments` (43–67) — pure grouping logic.
4. `build_chat_documents` (70–94) — turns segments into `Document`s with the
   metadata contract.
5. `index_pending_messages` (97–180) — the orchestrator: lock → query → build
   → purge → ingest → stamp → commit → unlock.

### `INDEXER_LOCK_KEY` and the dedicated-connection advisory lock (lines 30–36, 129–180)

**What**: A Postgres *session-level* advisory lock (`pg_try_advisory_lock` /
`pg_advisory_unlock`), taken on a **dedicated** `engine.connect()` connection
that is separate from the SQLAlchemy ORM `Session` used to do the actual
query/update work.

**Why**: Two things can trigger a concurrent run of this function: (a) the
default taskiq deployment runs 2 worker processes, and a cron tick can land on
both around the same time; (b) `RedisStreamBroker` redelivers a message if a
consumer doesn't ack within its idle timeout (10 min), so a slow-but-still-
running tick can get redelivered and executed a second time. The body's own
logic (purge → ingest → stamp) is only idempotent for **sequential** runs — if
two runs overlap, both can select the same un-indexed batch, both purge, and
both ingest, producing either duplicate vectors or a lost purge race. The
advisory lock makes concurrent runs mutually exclusive at the Postgres level
(session-scoped, so it does **not** depend on your application ever crashing
cleanly — if the process dies, Postgres releases the lock the instant the TCP
connection drops).

**The connection-affinity bug this fixes**: Postgres session advisory locks
are bound to the *physical connection*, not to a logical "session" object or
transaction. SQLAlchemy's `Session` (via `SessionLocal`) checks a connection
out of a pool, and **a `commit()` can return that connection to the pool** and
later check out a *different* physical connection for the next statement. If
you took the lock on `db.execute(...)` (the ORM session) and later tried to
unlock using the same `db` object after a `commit()` had happened in between,
you could be issuing the unlock on a different physical connection than the
one that holds the lock. Postgres would silently no-op (log a WARNING, "you
don't own a lock of this type") and the lock would leak forever — every future
tick would then see the lock "held" and skip, permanently wedging the
indexer with zero visible errors. That's why `lock_conn = engine.connect()` is
opened **outside** and **independently of** `session_factory()`, held for the
entire function body, and only that same `lock_conn` ever issues the unlock.

**Gotchas**:
- `got` is tracked separately from "did we open the connection" so the
  `finally` block only calls `pg_advisory_unlock` if `pg_try_advisory_lock`
  actually returned `true` — unlocking a lock you never held also produces the
  WARNING spam.
- The inner `try/finally` inside the outer `finally` (176–180) guarantees
  `lock_conn.close()` runs even if the unlock call itself raises.
- `pg_try_advisory_lock` (not the blocking `pg_advisory_lock`) is used
  deliberately — a losing run should return `0` and let the next cron tick
  retry, not block the worker thread waiting for the lock.

### `build_chat_segments(messages, *, gap_seconds, max_messages)` (43–67)

**What**: Groups a flat list of `Message` rows into per-channel lists
("segments"), where a new segment starts on: (1) a channel change, (2) an
inactivity gap greater than `gap_seconds` since the previous message in the
same channel, or (3) the current segment reaching `max_messages`.

**Why**: A segment, not a single message, is the retrieval unit. The comment
cites SeCom-style research: topic-coherent multi-turn segments retrieve better
than embedding individual messages (a single message like "yeah, that one" is
useless out of context). An inactivity gap is the cheapest *online-safe*
proxy for a topic boundary — it needs no extra LLM call or embedding
similarity computation, just a timestamp comparison.

**Mechanics**: messages are first bucketed by `channel_id` into a
`defaultdict(list)`, each channel's list is sorted by `sent_at`, then a single
pass builds `current` and flushes it into `segments` whenever a boundary
condition trips *before* appending the triggering message (so the message
that exceeded the gap or the cap starts the *next* segment, not the one being
closed).

**Gotcha**: `gap_exceeded` is computed against `current[-1].sent_at`, i.e. the
gap is measured from the previous message in the *segment*, not from the
first message — so a slow drip of messages each just under the gap threshold
never splits, even if the total elapsed time across the segment is large.

### `build_chat_documents(messages, chunk_size, chunk_overlap, *, gap_seconds, max_messages)` (70–94)

**What**: Converts segments into `Document` objects ready for Milvus
ingestion. One `Document` per segment, *unless* the segment's rendered text
exceeds `chunk_size`, in which case `RecursiveCharacterTextSplitter` further
splits it into multiple `Document`s (`chunk_index` 0, 1, 2…).

**Text format**: each message is rendered as `"{role}: {message_text(m)}"`
joined with `\n`, where `role` comes from `_role_str` (handles both a
`MessageRole` enum — `.value` — and a plain string, so it works against both
the real ORM `Message` and the `SimpleNamespace` test doubles used in unit
tests) and `message_text` normalizes `Message.content` (plain string or
ProseMirror JSON) into plain text (see `rag/message_text.py`, exercised by
`tests/rag/test_message_text.py`).

**The metadata contract** (83–90) — this is the part you must be able to
recite:
- `chatroom_id`: `str(segment[0].channel_id)`. Scopes chat vectors by
  channel for retrieval filtering. No `workspace_id` is stored because
  `channel_id` is already globally unique on this branch's schema (see the
  module docstring) — a workspace join isn't needed to disambiguate.
- `source`: literal `"chat"` — the discriminator that separates chat vectors
  from file-upload vectors in the single shared Milvus collection.
- `segment_id`: a fresh `uuid.uuid4()` per segment — a stable handle for one
  logical conversation window (shared across all chunk-index pieces of that
  segment).
- `message_ids`: **the full list** of every message's `str(id)` that
  contributed to this segment (not just the first or last). **Why it matters**:
  this is the join key that lets `delete_chat_segments_for_messages` (in
  `rag/vector_store.py`) find and purge *any* previously-ingested vector that
  covers *any* of a given batch of message ids — you don't need to know which
  segment a message ended up in ahead of time, you just ask "delete anything
  whose `message_ids` overlaps this set." It's also how `RAGChain`'s
  tail-dedupe (see `test_chat_recall_dedupe.py`) drops a retrieved chat vector
  when one of its member messages is already present in the un-indexed
  recency tail injected directly into the prompt — matching prevents the same
  conversation content from appearing twice in context.
- `sent_at_start` / `sent_at_end`: ISO timestamps bracketing the segment,
  used by chat-recall re-ranking (`rag/retrieval/chat_selection.py`) for
  time-decay scoring.
- `chunk_index`: added per split piece, in the outer loop (92–93), not in
  `meta` itself — every piece of one segment shares the same `meta` dict via
  `{**meta, "chunk_index": i}`.

**Gotcha**: `pieces = splitter.split_text(text) or [text]` — if the splitter
somehow returns an empty list (e.g. a segment made only of whitespace), the
`or [text]` fallback still emits one `Document` rather than silently dropping
the segment.

### `index_pending_messages(...)` (97–180)

**What**: One batch of the actual indexing work: lock → select un-indexed
settled messages → build documents → purge stale vectors for those messages →
ingest fresh vectors → stamp `indexed_at` → commit. Returns the count of
messages indexed (0 if nothing to do or the lock was contended).

**The "settled" cutoff**: `cutoff = utcnow() - timedelta(seconds=grace_seconds)`,
and the query filters `Message.sent_at < cutoff`. Only messages older than
`grace_seconds` are eligible. **Why**: this gives an in-flight conversation
time to be captured by the un-indexed recency tail (the small window of most
recent messages injected directly as chat context without going through
retrieval) before it becomes a candidate for the vector index — you don't
want the indexer racing a user's still-typing conversation.

**Purge → ingest → stamp ordering, and why it's lose-safe** (documented
in the docstring at 111–114): the three steps are NOT wrapped in one atomic
DB+Milvus transaction — Milvus and Postgres are two separate systems, no
2-phase commit is possible. So the design accepts that a crash mid-run must
fail toward *safe re-processing*, never toward *silent data loss* or
*duplicate vectors*:
- If the process crashes **before** the purge, nothing has changed — next
  tick reprocesses the same batch from scratch. Fine.
- If it crashes **between** purge and ingest, Milvus is now missing vectors
  for those messages, but `indexed_at` was never stamped — so the next tick
  picks the same messages up again (still `indexed_at IS NULL`) and
  re-ingests them. Purge already ran, so there's nothing stale to worry
  about.
- If it crashes **after** ingest but **before** `db.commit()` stamps
  `indexed_at`, the *newly-ingested* vectors exist in Milvus but Postgres
  still thinks the messages are unindexed. The next tick will select the same
  messages again, and its own **pre-ingest purge** — matching on
  `message_ids` — deletes those "orphaned" vectors before re-ingesting.
  That's the whole reason the purge always runs *before* ingest on every
  single tick, even though logically you might expect "only purge if
  retrying": the purge is what makes an accidental double-ingest a no-op
  instead of a duplicate.
- The only way to get silent duplication is two *concurrent* runs racing each
  other around this exact window — which is precisely what the advisory lock
  in §1 rules out.

**The mapper-registration imports** (116–120):
```python
from chat.model import Message
import workspace.model   # noqa: F401  (Channel, Workspace)
import filesystem.model  # noqa: F401  (File)
```
**Why**: the taskiq worker process is deliberately minimal — it does not
import the full FastAPI `app` module graph, so SQLAlchemy's declarative
mapper registry doesn't automatically know about `Channel`, `Workspace`, or
`File` unless *something* imports those modules first. `Message` has
relationship attributes (`Message.channel`, `Message.files`) that reference
those classes by name; SQLAlchemy resolves relationship targets lazily via
the mapper registry, and if `Channel`/`File` were never imported anywhere in
the process, `configure_mappers()` raises at first use. These two imports
exist purely for their side effect of registering those classes — that's why
they're `# noqa: F401` (unused-import lint suppression) instead of being used
directly. If you ever see `InvalidRequestError: ... expression 'Channel'
failed to locate a name` from a taskiq worker, this is the pattern to reach
for: import the module that defines the missing mapped class somewhere before
the query runs. (Compare `broker.py`'s `WORKER_STARTUP` hook, §4 below, which
solves the same class of problem process-wide via
`utils.import_sa_models.import_sa_models()` — this file's local imports are a
belt-and-suspenders guard scoped to exactly what this function touches.)

**`session_factory=None` default** (123–125): defaults to the real
`SessionLocal` via a **lazy import inside the function body**, not a module-
level default argument. This is a dependency-injection seam for tests — unit
tests pass `ingest=`/`purge=` fakes and can pass a custom `session_factory`
too, without ever importing `database` at module load time (which would force
a live DB connection just to import `chat_indexing.py`).

### Self-test

**Q: Two taskiq workers both fire the cron at 12:00:00 and 12:00:01. What
stops them from double-ingesting the same batch of messages?**
A: The session-level Postgres advisory lock at `INDEXER_LOCK_KEY`, taken on a
dedicated connection before the batch query runs. The second run's
`pg_try_advisory_lock` returns `false`, it logs and returns `0` without
touching the DB batch or Milvus.

**Q: Why is the advisory lock taken on `engine.connect()` instead of on the
`db` session object already open in the function?**
A: Because `db.commit()` can return the ORM session's pooled connection and
check out a different one afterward. Unlocking on the wrong physical
connection silently no-ops in Postgres, leaking the lock forever. The lock
must live on a connection that's never handed back to the pool mid-function.

**Q: If the process crashes right after `ingest(docs)` succeeds but before
`db.commit()`, what happens to those vectors?**
A: They sit in Milvus, "orphaned" — Postgres still shows `indexed_at IS NULL`
for those messages. The next tick re-selects the same messages, and its purge
step (which runs *before* ingest, matching on `message_ids`) deletes those
orphaned vectors before re-ingesting fresh ones. No duplicates, no data loss.

**Q: Why does `message_ids` carry every message in the segment instead of
just one representative id?**
A: It's the join key used by both the purge (delete any vector touching any
of a batch of message ids) and the RAGChain tail-dedupe (drop a retrieved
chat vector if any of its member messages is already in the directly-injected
recency tail). Storing only one id would make both of those lookups miss
whenever the matching message happens to be a different member of the
segment.

**Q: Why are `workspace.model` and `filesystem.model` imported inside
`index_pending_messages` when they're never referenced by name in the
function body?**
A: Pure import-time side effect — they register `Channel`/`Workspace`/`File`
with SQLAlchemy's mapper registry so `Message.channel` and `Message.files`
relationships can resolve. The minimal taskiq worker process doesn't import
the full app, so without this, the first query touching those relationships
would raise a mapper configuration error.

---

## 2. `src/processing/chat_tasks.py`

### Job in one sentence
Declare the taskiq cron task that drives the indexer above, draining a
backlog across multiple batches within one tick instead of leaking one batch
per cron interval.

### Read it in this order
1. Module docstring (1–6).
2. `_CRON` (18) — the schedule string.
3. `@broker.task(...)` decorator on `index_chat_messages` (21) — the retry
   labels.
4. The function body (22–45) — the drain loop.

### The cron declaration (line 18, 21)

```python
_CRON = f"*/{max(global_rag_config.chat_index_interval_minutes, 1)} * * * *"

@broker.task(schedule=[{"cron": _CRON}], retry_on_error=True, max_retries=3)
async def index_chat_messages() -> int:
```

**What**: `_CRON` is evaluated **once, at import time** (module load), not
per-tick — it bakes in whatever `global_rag_config.chat_index_interval_minutes`
was at process startup. If you change that config value at runtime (e.g. via
a hot-reloadable settings row), the scheduler will **not** pick up the new
interval until the scheduler process restarts. `max(..., 1)` guards against a
misconfigured `0`-or-negative interval producing an invalid or nonsensical
cron expression.

The `schedule=[{"cron": ...}]` label is what `LabelScheduleSource` (see
`scheduler.py`, §4) discovers automatically — it's a taskiq convention: any
`@broker.task` with a `schedule` label becomes a cron entry with zero extra
registration code.

### `retry_on_error=True, max_retries=3` — and why retries are immediate (comment at 24–28)

**What**: If `index_chat_messages` raises, `SmartRetryWithCallbackMiddleware`
(see `broker.py`, §4) retries it up to 3 times.

**The gotcha you must know**: taskiq's `SmartRetryMiddleware` normally
computes a delay label (exponential backoff) between retries, but
**`RedisStreamBroker` does not honor delay labels at all** — it has no
built-in delayed-redelivery mechanism, so a "retry with backoff" actually
executes as an **immediate** re-attempt with no wait. This means the 3
retries in this task exist purely to absorb *transient* failures (a Milvus
timeout, a momentary embedding-API hiccup) within the same tick, back to
back. They are explicitly **not** a substitute for real backoff — the
docstring says the "next cron tick remains the durable fallback": if all 3
immediate retries fail (e.g. Milvus is actually down), the task gives up for
this tick, and the *next* scheduled cron tick (whatever
`chat_index_interval_minutes` minutes later) becomes the real retry
mechanism with natural spacing.

### The drain loop (29–45)

```python
total = 0
for _ in range(max(global_rag_config.chat_index_max_batches, 1)):
    n = await asyncio.to_thread(index_pending_messages, ...)
    total += n
    if n < global_rag_config.chat_index_batch_size:
        break
```

**What**: calls `index_pending_messages` up to `chat_index_max_batches` times
in a loop, stopping early the moment a call returns fewer messages than
`chat_index_batch_size` (meaning the backlog is exhausted — a full batch
means there's likely more work waiting).

**Why**: without this loop, a burst of messages (say, a busy day generates
5,000 un-indexed messages but `chat_index_batch_size=500`) would only clear
at a rate of one batch (500) per cron tick — i.e. `chat_index_interval_minutes`
apart — taking 10 ticks to catch up, during which retrieval quality for chat
history is degraded. The drain loop clears the whole backlog (bounded by
`chat_index_max_batches`) inside a single tick.

**`asyncio.to_thread`**: `index_pending_messages` is a fully synchronous,
blocking function (sync SQLAlchemy `Session`, sync Milvus client calls, sync
embedding calls). Running it directly inside the `async def` task would block
the single-threaded taskiq event loop, starving every other concurrently
scheduled task on that worker. `asyncio.to_thread` offloads it to a thread
pool so the event loop stays responsive.

**Gotcha in `test_tick_drains_multiple_batches`**: the test monkeypatches
`chat_tasks.index_pending_messages` (the *name bound in this module*, not
`processing.chat_indexing.index_pending_messages` where it's defined) — this
only works because `chat_tasks.py` does `from processing.chat_indexing import
index_pending_messages` at the top, binding a local name in its own module
namespace. Patch the wrong target (the origin module) and the drain loop
would still call the real function. See §2 of the tests chapter for the
general rule this illustrates.

### Self-test

**Q: You bump `chat_index_interval_minutes` in a running config. Does the
cron schedule change immediately?**
A: No. `_CRON` is computed once at module import time. The scheduler process
must restart to pick up the new interval.

**Q: The Milvus insert fails twice in a row inside one cron tick, then
succeeds on retry 3. How long did the worker wait between retries?**
A: Effectively zero — `RedisStreamBroker` ignores taskiq's delay/backoff
labels, so all `SmartRetryMiddleware` retries against this broker are
immediate, back-to-back attempts within the same tick.

**Q: Why does the loop break when `n < chat_index_batch_size` instead of
running the full `chat_index_max_batches` every tick?**
A: `n < batch_size` is a cheap signal that the query returned fewer rows than
it asked for, i.e. there's no more backlog right now — continuing to loop
would just re-run empty/near-empty queries for no benefit.

---

## 3. `src/processing/tasks.py` — `process_file`

### Job in one sentence
The single taskiq entrypoint for turning an uploaded `File` row into
retrieval-ready content: atomically claim the file, download it from
workspace-scoped MinIO storage, dispatch to the document or image processor
by MIME type, and stamp the terminal status.

### Read it in this order
1. Module docstring + imports (1–14).
2. The claim-update block (36–47).
3. The claim-result branch (49–59).
4. Per-file `MinIOFileSystem` construction (66–74).
5. The dispatch + success/failure handling (76–109).

### The claim-update, and its documented weakness (17, 30–35, 36–47)

```python
result = db.execute(
    sa_update(File)
    .where(File.id == file_id, File.processing_status.in_(
        [FileStatus.UPLOADED, FileStatus.PROCESSING_FAILED]))
    .values(processing_status=FileStatus.UPLOADED)
)
db.commit()
if result.rowcount == 0:
    ...  # skip, already claimed/indexed/gone
```

**What**: a single `UPDATE ... WHERE status IN (...)` conditioned on the
row's *current* state, checked via `result.rowcount`. This is the standard
"claim by conditional update" pattern for avoiding a worker processing a file
that's already being (or has already been) processed.

**The documented weakness** (comment at 31–35): the intent is a proper
`UPLOADED|FAILED → PROCESSING` state transition, but **`FileStatus` has no
`PROCESSING` enum member** (owned by the filesystem/upload-system
contributor, flagged as a known issue, not something you patch here). Because
there's no distinct in-flight state, the update re-asserts
`FileStatus.UPLOADED` — i.e. it writes the same value the row already had (or
transitions `PROCESSING_FAILED → UPLOADED`). That means the `rowcount == 0`
gate still correctly *filters out* files that are already `INDEXED` or
`PROCESSING_FAILED`-but-already-reclaimed-by-someone-else at the instant this
statement runs, but it provides **no mutual exclusion** — two workers racing
this same `UPDATE` statement on the same row within the same window can
*both* get `rowcount == 1` (an UPDATE that changes `UPLOADED → UPLOADED` still
reports 1 row matched/updated in Postgres), because there's no third state to
serialize on. **Why it's still safe**: `process_document`'s pre-ingest
`delete_file_chunks` purge (see §5 below) makes a duplicate run merely
wasteful (re-downloads, re-parses, re-embeds, but the final Milvus state is
identical because the second run's purge clears whatever the first run just
inserted, or vice versa depending on ordering) — it costs compute, not
correctness. This is a lower bar than the chat indexer's advisory lock
because file processing volume/collision risk is much lower and a real fix
(adding the enum member) belongs to the filesystem owner.

**Gotcha**: don't "fix" this by adding your own ad hoc lock or state without
coordinating — the comment explicitly says the missing enum member has been
reported upstream; duplicating a workaround here would create a second
source of truth to reconcile later.

### Sync `SessionLocal`, not `AsyncSessionLocal` (21–23)

**What**: `with SessionLocal() as db:` — the plain, synchronous session
factory (see `src/database.py`), even though `process_file` itself is
`async def`.

**Why**: the comment is explicit — "the body is written sync-style (plain
execute/commit, and the processors take a sync `Session`)". `process_document`
and `process_image` both type-hint `db: Session` (sync) and call
`db.commit()` directly with no `await`. Using `AsyncSessionLocal` here would
require `await db.commit()`, `await db.execute(...)` throughout, which the
processor functions don't do. Mixing sync ORM calls onto an async session
object doesn't work — you'd get either blocking-call-in-event-loop warnings
or outright errors. This is a deliberate, consistent choice across the whole
processing subpackage, not an oversight.

### Per-file `MinIOFileSystem`, and why `uri` is relative (66–74)

```python
storage = MinIOFileSystem(
    cfg().minio,
    workspace_id=file_record.workspace_id,
    channel_id=file_record.channel_id,
)
```

**What**: a brand-new `MinIOFileSystem` instance is constructed **per file**,
scoped to that file's own `workspace_id`/`channel_id`, rather than one
shared/global filesystem client.

**Why**: on this branch, `File.uri` is stored as a **relative virtual path**
(e.g. `"minio://<parent>/<name>"`), not an absolute bucket path. The
filesystem's `split_path` method re-prepends `{bucket}/{workspace}/{channel}`
onto whatever relative path it's given — so for that reconstruction to
produce the right absolute object key, the filesystem instance must already
know which workspace/channel it's scoped to. A single shared/global instance
would have no way to know the right prefix for an arbitrary file unless that
scope were threaded through every call instead of through construction — the
chosen design pushes the scoping into the constructor once, so every
subsequent `storage._get_file(...)` call just uses the relative path as-is.
See `documents.py`'s comment (106–109): `rel_path =
str(file_record.uri).removeprefix("minio://")` — only the protocol prefix is
stripped; the workspace/channel prefixing happens inside `storage`, not here.

**Gotcha**: `download_file_to_path` (used by `images.py`, see §5) was "a dead
API" per the `documents.py` comment — `process_document` uses `_get_file`
instead. If you're extending `process_image`, check whether the storage
interface has since been reconciled; `images.py` still calls
`download_file_to_path`, which is an inconsistency worth flagging if you
touch that file (the TODO comment "update storage interface" at the top of
both `documents.py` and `images.py` marks this as known-unfinished).

### Dispatch and stamping (76–109)

**What**: routes to `processing.documents.process_document` or
`processing.images.process_image` based on
`cfg().files.document_mime_types` / `cfg().files.image_mime_types`
membership, imported **inline** (inside the `try` block, not at module top)
so importing `tasks.py` doesn't eagerly pull in `unstructured`/`Pillow`
unless a file of that type is actually being processed. An unrecognized MIME
type raises `ValueError` explicitly rather than silently no-op'ing.

On success: `file_record.processing_status = FileStatus.INDEXED` then
commit. Comment: `.status is not a column on this branch` — a reminder that
an older/other branch used a different attribute name (`status`); this branch
uses `processing_status`. Don't "helpfully" rename it back.

On exception: `db.rollback()` first (to discard any partial writes from the
failed processor), re-fetch `file_record` (it may have vanished — logged and
return if so), then set `processing_status = FileStatus.PROCESSING_FAILED`
and `processing_error = str(e)[:2048]`. That second assignment is annotated
`# not a mapped column yet — silently dropped until the filesystem owner adds
it (reported)` — i.e. **this line currently does nothing** (SQLAlchemy
silently ignores attribute assignments that aren't mapped columns unless
you've misconfigured something more surprising). It's left in place as
forward-documentation of intent and because it's harmless. Finally,
`raise` — re-raises the original exception so taskiq's retry middleware
(and any `on_failure` callback wiring, see `broker.py` §4) sees the failure.

### Self-test

**Q: Two workers both pick up `process_file` for the same file at nearly the
same instant. What actually stops corruption?**
A: Nothing stops both from "winning" the claim-update (no `PROCESSING` enum
member means no true exclusion state) — but `delete_file_chunks` runs before
every ingest, so whichever run finishes last leaves Milvus in a consistent
state. It's wasted compute, not a correctness bug.

**Q: Why is `process_file` an `async def` but uses `SessionLocal` (sync)
instead of `AsyncSessionLocal`?**
A: Because the processor functions it calls (`process_document`,
`process_image`) are written against a sync `Session` API (plain
`db.commit()`, no awaits) — mixing that with an async session wouldn't work.

**Q: Why is a new `MinIOFileSystem` constructed inside `process_file` for
every single file, instead of reusing one client?**
A: Because `File.uri` on this branch is a relative path, and
`MinIOFileSystem.split_path` needs to know the file's `workspace_id`/
`channel_id` (passed at construction) to reconstruct the correct absolute
bucket path. A single shared instance has no per-call way to carry that
scope.

**Q: `file_record.processing_error = str(e)[:2048]` — does this actually
persist the error message anywhere?**
A: No. `processing_error` is not a mapped column on this branch yet; the
assignment is silently dropped by the ORM. It's a documented known gap, not a
bug you introduced.

---

## 4. `src/processing/documents.py`

### Job in one sentence
Download a file from MinIO, extract text (via `unstructured` or a plaintext
fallback), chunk it into retrieval-ready `Document`s, purge any prior chunks
for that file, and ingest the fresh chunks into Milvus.

### Read it in this order
1. Module docstring + `_NOISE_CATEGORIES` (1–20).
2. `_partition_elements` / `_section_title_of` (23–34).
3. `build_chunk_documents` (37–94) — the chunking entrypoint, both strategies.
4. `process_document` (98–168) — the orchestrator.
5. `_fallback_extract` (171–183).

### `_get_file` download, and why `uri` handling matters (106–111)

```python
rel_path = str(file_record.uri).removeprefix("minio://")
await storage._get_file(rel_path, tmp_path)
```
Downloads to a `tempfile.NamedTemporaryFile` created with `delete=False` (so
the file survives being closed by the `with` block, since it needs to be
reopened by `unstructured`/PDF libraries afterward) with the original
extension preserved (`suffix=ext`) — several parsers dispatch on file
extension. The `finally` block (166–168) unlinks the temp file unconditionally,
so a failure partway through parsing/chunking/ingesting still cleans up disk.

### `_partition_elements` (23–27)

Thin wrapper over `unstructured.partition.auto.partition(filename=...,
strategy="fast")`. Raises `ImportError` naturally if `unstructured` isn't
installed — the caller (`process_document`) catches specifically `ImportError`
to fall back to `_fallback_extract`, so any *other* exception from `partition`
(a malformed file, an unsupported format) is **not** swallowed and propagates
up to `process_file`'s failure handler.

### `build_chunk_documents(elements, *, base_metadata, config=None)` (37–94) — the two chunking strategies

**What**: the single chunking entrypoint, config-gated between two mutually
exclusive strategies via `cfg.chunking_strategy`:

**`"recursive"` (legacy, default — 77–94)**: one `Document` per `unstructured`
element (paragraph/title/etc.), with `RecursiveCharacterTextSplitter` only
ever *splitting* oversized elements further — it never merges short
elements together, so a document with many short paragraphs produces many
small fragment chunks. The comment explicitly flags this must stay a
**faithful reproduction of the pre-2026-07 corpus** — this is the ablation
baseline everything else is measured against, so don't casually "improve" it.

**`"by_title"` (37–75)**: filters out `_NOISE_CATEGORIES` elements first
(`Header`, `Footer`, `PageBreak`, `Image` — running boilerplate that hurts
retrieval by winning similarity matches against genuinely irrelevant chunks),
then uses `unstructured.chunking.title.chunk_by_title` to *pack/merge*
elements into sections bounded by `max_characters=cfg.chunk_size`, with
`new_after_n_chars=min(800, cfg.chunk_size)` (soft target before force-
starting a new chunk) and `combine_text_under_n_chars=200` (merge short
fragments into a neighbor rather than emitting a tiny chunk). Each resulting
chunk's section title is extracted via `_section_title_of` (30–34, scans
`chunk.metadata.orig_elements` for a `Title`-category element with non-empty
text) and optionally prepended to the chunk text as `[Section]\n...` when
`cfg.chunk_prepend_section_title` is set — giving the embedding model a
topical anchor per chunk.

**Why the noise filter is strategy-gated, not global**: applying it
unconditionally to the legacy path would silently change the reproduction
corpus that `"recursive"` is supposed to hold fixed — the noise filter is
new behavior, deliberately confined to the new opt-in path.

**Gotcha**: the noise filter runs *before* `chunk_by_title`, so a `Header`
element never gets a chance to contribute its (usually junk) text to any
merged section — it's fully excluded, not just down-weighted.

### `process_document` orchestration and `delete_file_chunks` idempotency (98–168)

Same "purge before ingest" idempotency pattern as the chat indexer, but
scoped by `(file_id, workspace_id)` instead of by message ids:

```python
from rag.vector_store import delete_file_chunks
delete_file_chunks(str(file_record.id), workspace_id=str(file_record.workspace_id))
from rag.ingestion import ingest_file_chunks
ingest_file_chunks(chunks, str(file_record.workspace_id), str(file_record.id))
```

**Why** (comment at 145–148): "Milvus has no unique constraint on
`(file_id, chunk_index)` — re-ingesting without this would duplicate
chunks." Any retry (whether from the claim-update's lack of mutual exclusion
in `tasks.py`, or a legitimately re-triggered reprocess) purges stale chunks
for that file before adding new ones, so retries never leave duplicate or
orphaned vectors behind.

**No-text-extracted path** (135–139): if `chunks` ends up empty (e.g. a
scanned image-only PDF with no OCR), the function logs a warning, sets
`file_record.chunk_count = 0` (also flagged as "not a mapped column yet —
silently dropped", same caveat as `tasks.py`), commits, and **returns early**
— it does not call `delete_file_chunks`/`ingest_file_chunks` at all in this
branch, since there's nothing to purge-and-replace for a file that never had
chunks in the first place... actually note it *skips* the purge here too, so
if a file previously had chunks and a *reprocess* now extracts zero text
(e.g. after a content change), stale chunks from a prior successful run would
be left behind. Worth flagging if you ever touch this path.

**`chunk_index` metadata** (142–143): added to every chunk's metadata as a
second pass after chunking, uniformly across both strategies — this is where
ordinal position within the file gets attached, separate from whatever
`page_number`/`section` each strategy already set.

### `_fallback_extract` (171–183)

Only handles `text/plain` and `text/markdown` by reading the file directly as
UTF-8 (`errors="replace"` so a malformed byte doesn't crash the whole
pipeline). Anything else logs a warning and returns an empty list — meaning
`process_document`'s fallback path produces zero chunks for any binary format
(PDF, DOCX, images) when `unstructured` isn't installed. This fallback exists
so the pipeline degrades gracefully rather than crashing when the (large,
optional) `unstructured` dependency isn't present in a given environment.

### `src/processing/images.py` (brief)

**Job**: download an image, generate a JPEG thumbnail via Pillow, upload the
thumbnail, stamp `thumbnail_storage_key`. Converts `RGBA`/`P` mode images to
`RGB` first (comment: "faster to thumbnail a 3-channel image" — also
necessary because JPEG has no alpha channel). `THUMBNAIL_SIZE` is read from
`cfg().files.thumbnail_size` **at module import time** (line 13, module-level
constant) rather than per-call — same "baked in at import" caveat as
`chat_tasks.py`'s `_CRON`: changing the config at runtime won't affect an
already-running worker process. Uses `storage.download_file_to_path(...)`
(the API `documents.py`'s comment calls "a dead API" — worth reconciling if
you touch this file) rather than `_get_file`. No purge-before-write
idempotency concern here since thumbnails just overwrite by fixed key
(`{file_id.hex}_thumb.jpg`), and `db.commit()` only ever sets one field.

### Self-test

**Q: Why does the `"recursive"` chunking strategy never merge short
elements together, while `"by_title"` does?**
A: `"recursive"` must stay byte-for-byte faithful to the pre-2026-07 corpus
so it remains a valid baseline for ablation comparisons; `RecursiveCharacterTextSplitter.split_documents` only splits, never merges. `"by_title"` is the
new opt-in path where `chunk_by_title`'s packing behavior is allowed to
differ.

**Q: Two retries of `process_document` run back-to-back for the same file.
Why don't you end up with duplicate vectors in Milvus?**
A: `delete_file_chunks(file_id, workspace_id=...)` runs immediately before
`ingest_file_chunks` on every single run — any chunks from a prior attempt
for that exact file are purged first.

**Q: `_NOISE_CATEGORIES` filters `Header`, `Footer`, `PageBreak`, `Image`.
Why does this filtering only apply on the `"by_title"` path?**
A: Applying it globally would change the output of the legacy `"recursive"`
path, which is deliberately held fixed as the reproduction baseline for
comparing chunking strategies.

**Q: What happens to Milvus if a file that previously ingested 40 chunks is
reprocessed and the new extraction yields zero chunks?**
A: The early-return branch (135–139) sets `chunk_count = 0` and returns
*without* calling `delete_file_chunks` — so the previous 40 chunks are left
stale in Milvus. This is a real gap, not intentional idempotency.

---

## 5. `src/broker.py` + `src/scheduler.py`

### Job in one sentence
`broker.py` wires up the taskiq broker (Redis-backed in production, in-memory
for tests) that every `@broker.task` in this codebase registers against;
`scheduler.py` is the separate process entrypoint that turns `schedule=[...]`
task labels into actual cron firings.

### Read it in this order
1. `broker.py`: `register_callback` / `_callbacks_registry` (8–20).
2. `SmartRetryWithCallbackMiddleware.on_error` (23–48).
3. The `broker` construction + `InMemoryBroker` test substitution (51–65).
4. `WORKER_STARTUP` hook (68–71).
5. `scheduler.py` in full (13 lines).

### `SmartRetryWithCallbackMiddleware` (23–48)

**What**: extends taskiq's built-in `SmartRetryMiddleware` (which handles the
actual retry-scheduling logic) to additionally fire a registered `on_failure`
callback once retries are **exhausted** — i.e. this is a "dead letter" hook,
not a per-attempt hook.

```python
async def on_error(self, message, result, exception):
    retry_count = int(message.labels.get("_retries", 0)) + 1
    max_retries = int(message.labels.get("max_retries", self.default_retry_count))
    await super().on_error(message, result, exception)
    if not self.is_retry_on_error(message):
        return
    if retry_count >= max_retries:
        callback_name = message.labels.get("on_failure")
        if callback_name and callback_name in _callbacks_registry:
            ...
```

**Critical gotcha**: `if not self.is_retry_on_error(message): return` — this
middleware's entire on-error handling (including the callback logic) is a
no-op for any task that was **not** declared with `retry_on_error=True`. Look
back at `chat_tasks.py`'s `@broker.task(schedule=[...], retry_on_error=True,
max_retries=3)` — that task opted in. `process_file` in `tasks.py`, by
contrast, is declared as plain `@broker.task()` with **no** `retry_on_error`
label (see the `# TODO: retry, backoff, timeout..` comment right above it) —
so for `process_file`, `is_retry_on_error` is false, `super().on_error()`
still runs (base retry bookkeeping / logging), but this subclass's extra
callback-firing logic is skipped entirely regardless of whether anything is
registered via `register_callback`. If you want `process_file` failures to
trigger an `on_failure` callback, you must add `retry_on_error=True` to its
decorator first — the callback registry alone does nothing without that
label.

`register_callback` (11–20) just populates a plain module-level dict
(`_callbacks_registry`) keyed by function name, with a guard against
silently overwriting a different callable already registered under the same
name (raises `ValueError` instead). There's currently no caller of
`register_callback` anywhere visible in this pipeline walkthrough — it's
infrastructure waiting for a consumer; check `tests/utils/test_on_failure.py`
for how it's exercised in isolation.

### The broker construction and `InMemoryBroker` substitution (51–65)

```python
broker: AsyncBroker = (
    RedisStreamBroker(url=cfg().redis.url)
    .with_result_backend(RedisAsyncResultBackend(redis_url=cfg().redis.url, result_ex_time=3600))
    .with_middlewares(SmartRetryWithCallbackMiddleware())
)
if cfg().is_test:
    broker = InMemoryBroker(await_inplace=True).with_middlewares(*broker.middlewares)
```

**What**: production broker is `RedisStreamBroker` (Redis Streams as the
task queue, with a 1-hour result TTL). If `cfg().is_test` is true (driven by
`IS_TEST` env var — see the tests chapter §1), the module-level `broker` name
is **rebound** to `InMemoryBroker(await_inplace=True)`, carrying over the
same middleware stack (`*broker.middlewares`, unpacking whatever was already
attached to the Redis-backed instance before rebinding). `await_inplace=True`
means `.kiq()` calls (taskiq's "enqueue" API) execute the task **synchronously
in-process** instead of round-tripping through a broker at all — essential
for unit tests that call `some_task.kiq(...)` and want to assert on the
result immediately, with no Redis dependency and no timing race.

**Gotcha**: this substitution happens at **import time** of `broker.py`,
which means `cfg().is_test` must already reflect the right value (i.e.
`IS_TEST` must already be set in the environment) before `broker.py` is
first imported anywhere in the process — this is exactly why pytest's config
sets `IS_TEST=True` via `pytest-env` (see tests chapter) rather than relying
on a fixture, which would run too late.

### `WORKER_STARTUP` hook (68–71)

```python
@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(_state):
    from utils.import_sa_models import import_sa_models
    import_sa_models()
```

**What**: fires once when a taskiq worker **process** boots (not per-task).
Calls a helper that imports every SQLAlchemy-mapped model module up front.
**Why**: this is the process-wide fix for the same mapper-registration
problem `chat_indexing.py` patches locally with its own inline imports (§1
above) — since the worker process never imports the full `app` module graph,
without this hook *any* task touching an ORM relationship whose target class
was never imported would hit `configure_mappers()` errors the first time it's
used. `import_sa_models()` front-loads that cost once at startup instead of
depending on each task file remembering its own local imports (belt-and-
suspenders: `chat_indexing.py`'s local imports still exist as a defense in
case this hook is ever skipped, e.g. in `InMemoryBroker` test mode where
`WORKER_STARTUP` may not fire the same way).

### `scheduler.py` (13 lines, read in full)

```python
scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])
```
**What**: a **separate process entrypoint**, run via
`taskiq scheduler scheduler:scheduler <task-modules> --app-dir=src` (per the
module docstring) — this is not the worker process, it's the thing that
watches for `schedule=[...]` labels and fires the corresponding task onto the
broker at the right time. `LabelScheduleSource(broker)` means **any**
`@broker.task(schedule=[...])` anywhere in the imported task modules is
auto-discovered — no manual registration list to keep in sync. `chat_tasks
.index_chat_messages` is the only current example. If you add a second
cron task anywhere, giving it a `schedule=` label on the `@broker.task`
decorator is sufficient; you do not need to touch `scheduler.py` at all.

**Gotcha**: the scheduler process and the worker process(es) are *separate
deployables* — the scheduler only decides *when* to fire, the worker(s)
actually execute. If you run `<task-modules>` inconsistently between the two
(e.g. the scheduler's `--app-dir`/module list doesn't import
`processing.chat_tasks`), the cron entry silently never gets registered, with
no error — it just never fires.

### Self-test

**Q: You add `retry_on_error=True` to nothing and register an `on_failure`
callback for `process_file` via `register_callback`. Does it ever fire?**
A: No. `SmartRetryWithCallbackMiddleware.on_error` returns immediately for
any task not declared with `retry_on_error=True` — the callback registry is
irrelevant if that label is missing.

**Q: Why does `broker.py` rebind `broker` to `InMemoryBroker` based on
`cfg().is_test` instead of a pytest fixture doing it?**
A: The rebinding must happen before any module imports `broker` and starts
using it for `.kiq()` calls or decorators — that happens at import time.
`IS_TEST` is set via `pytest-env` before collection even starts, so by the
time any test module imports `broker`, `cfg().is_test` already reflects it. A
fixture would run too late — modules importing `broker` at their own import
time would already have bound to the real Redis broker.

**Q: You add a new `@broker.task(schedule=[{"cron": "0 * * * *"}])` task in a
new module. What else do you need to change in `scheduler.py`?**
A: Nothing, as long as the scheduler process's module list (passed on its
CLI invocation) imports the new module so the decorator runs and registers
the label. `LabelScheduleSource` auto-discovers any `schedule=` label.

---

## 6. The known integration gap: nothing enqueues `process_file`

**Status**: `process_file` (in `tasks.py`) is a fully-implemented taskiq task
— claim, download, dispatch, stamp, all present and tested (see the tests
chapter §2 for `tests/processing/test_process_file.py`) — but **nothing in
this codebase currently calls `process_file.kiq(file_id)`** (or any
equivalent enqueue) after a file finishes uploading. This is the filesystem/
upload-system owner's integration hook — the upload endpoint that writes the
`File` row and stores the object in MinIO is expected to also enqueue this
task, and as of this branch it doesn't. This has been reported to that
owner; it is **not** something to silently patch by adding an enqueue call
inside `tasks.py` itself (that's not where it belongs) or inside the upload
router without coordinating — the fix is a one-line addition
(`await process_file.kiq(file.id)`) at the end of whatever endpoint currently
finalizes an upload, once you've confirmed with the owner where that call
should live.

**How to kick it manually** (for testing/demoing the pipeline end-to-end
without waiting for that integration):

```python
# from a Python shell with PYTHONPATH=src, or a one-off script:
import asyncio
from processing.tasks import process_file
import uuid

asyncio.run(process_file.kiq(uuid.UUID("...")))          # enqueue via the real broker
# or, to run it in-process without a broker/worker at all:
asyncio.run(process_file.original_func(uuid.UUID("...")))
```

`.kiq(...)` is taskiq's standard "send this task to the broker" call — it
requires a running worker process to actually pick it up (`taskiq worker
broker:broker --app-dir=src`, or similar, depending on how the project's
worker entrypoint is invoked). `.original_func(...)` — the pattern used
throughout the test suite (see `test_process_file.py`) — bypasses the broker
entirely and calls the plain async function directly, useful for manual
verification when you don't want to stand up Redis/a worker just to exercise
the pipeline once.

### Self-test

**Q: You just uploaded a file through the API and it never gets processed.
Is `process_file` broken?**
A: Almost certainly not — check whether anything actually enqueued it. As of
this branch, no upload endpoint calls `process_file.kiq(...)`; that wiring is
a known, reported gap owned by the filesystem contributor.

**Q: What's the fastest way to manually verify the document pipeline works
end-to-end for a specific `File` row, without standing up a worker process?**
A: `await process_file.original_func(file_id)` — calls the underlying async
function directly, in-process, bypassing the broker/worker entirely.
