# 07 — Integration Map

Concepts are explained once in `00-foundations.md`; this chapter points back with
`(→ 00 §n)` only where a concept term actually shows up in a seam.

Everything RAG code touches outside `src/rag/` and `src/processing/`, and everything
that touches back. This is the seam inventory: what we import from teammates, what we
mount into their routers, what tables/events/permission strings are shared, and the
cross-branch coordination debt that's tracked but not yet resolved on this working
tree (branch `feature/chat-message-memory`).

## 1. Inbound mounts — how our code gets wired into the app

**`workspace/router.py` mounts our two routers with three lines each.**
`src/workspace/router.py:8-9` imports `ask as channel_rag_router` from
`rag.router` and `workspace_ai as workspace_ai_router, channel_ai as
channel_ai_router` from `rag.settings_router`. The actual mount is one
`include_router` call per router:
```
channel.include_router(channel_rag_router)     # workspace/router.py:26
workspace.include_router(workspace_ai_router)   # workspace/router.py:27
channel.include_router(channel_ai_router)       # workspace/router.py:28
```
`channel` and `workspace` are `APIRouter`s with `prefix="/channels/{channel_id}"` /
`prefix="/workspaces/{workspace_id}"` and a `dependencies=[require_perms("channel:view")]`
/ `dependencies=[require_perms("workspace:view")]` respectively
(`workspace/router.py:12-19`) — every route we mount inherits that base permission
before our own `require(...)` deps run.

**`app.py`'s `Base.metadata.create_all(engine)` picks up `AiSettings` transitively, not
by direct import.** `app.py:19` imports `workspace.router`, which imports
`rag.router` (`workspace/router.py:8`), which imports `rag.rag_chain.RAGChain`
(`rag/router.py:36`), which imports `from .ai_settings import OVERRIDABLE`
(`rag/rag_chain.py:13`) — this import chain runs at module load, before
`Base.metadata.create_all(engine)` executes in the lifespan (`app.py:34`), so
`AiSettings(Base)` (`rag/ai_settings.py:34`) is already registered on `Base.metadata`
by the time `create_all` runs. There is no explicit `import rag` anywhere in `app.py` —
the registration is a side effect of `workspace.router`'s import graph. **Risk:** if
`rag.settings_router`'s import of `ai_settings` were ever removed without another path
still importing it before `create_all`, the `ai_settings` table would silently stop
being created on fresh DBs (no Alembic — see `docs/chat-memory-handoff.md`'s "No
Alembic" caveat).

**No RAG-specific lifespan hook exists.** `app.py`'s `lifespan` only calls
`Base.metadata.create_all(engine)` (`:34`) and `bind_chat_storage(...)` (`:36`); Milvus
connection setup is lazy (`_ensure_milvus_connection()`, called on first use from every
`vector_store.py` entry point) — there is no explicit "connect to Milvus at startup"
step.

### Self-test Q&A
- **Q: You delete `from .ai_settings import OVERRIDABLE` from `rag_chain.py`. Does
  `ai_settings` still get imported before `create_all` runs?**
  A: Only if some other import in the `workspace.router` → ... chain still reaches it —
  currently `rag/settings_router.py:14` (`from rag.ai_settings import ...`) is also in
  that chain via `workspace/router.py:9`, so removing just the `rag_chain.py` import
  wouldn't break it today, but it's a fragile, implicit guarantee, not an enforced one.
- **Q: If you wanted `/ask` to require a NEW permission on top of `channel:view` and
  `channel.message:send`, where would you add it?**
  A: In the `dependencies=[...]` list on the `@ask.post("/ask", ...)` decorator itself
  (`rag/router.py:145`) — never on the shared `channel` `APIRouter` (that would apply it
  to every other channel-scoped route too).
- **Q: Does mounting `channel_rag_router` under `channel` give `/ask` any workspace-id
  awareness for free?**
  A: No — `channel`'s prefix only supplies `channel_id`; `/ask`'s handler resolves
  `workspace_id` itself via `db.scalar(select(Channel.workspace_id)...)`
  (`rag/router.py:154-155`).

---

## 2. Outbound imports — what we pull from teammate modules

| import | from | used for | file:line | what breaks if the contract changes |
|---|---|---|---|---|
| `Message`, `MessageRole` | `chat.model` | reading the un-indexed tail, persisting Q/A rows | `rag/router.py:28`, `_load_unindexed_tail` `:73-81`, `_persist_exchange` `:109-112` | If `Message.content` stops being a plain `str` (rich-msg's JSONB migration), `_persist_exchange`'s direct `content=answer` assignment breaks — see §5. If `MessageRole.SYSTEM` is renamed/removed, the tail-skip filter (`:78`) silently stops skipping system rows. |
| `sio` | `chat.realtime` | broadcasting the `ai_message` event | `rag/router.py:127` (local import, comment: "teammate module: import-only, never modified") | If the room-naming convention `f"channel:{channel_id}"` changes on the chat side, our broadcast reaches nobody (best-effort, so it fails silently — see §3). |
| `require_perms as require` | `workspace` | permission gating on `/ask` and ai-config endpoints | `rag/router.py:32`, `rag/settings_router.py:15` | If `require_perms`'s signature changes (e.g. adds a required kwarg), every RAG route mount breaks at import time, not just at request time. |
| `Channel` | `workspace.model` | resolving `workspace_id` from `channel_id` | `rag/router.py:33`, `settings_router.py:16` | If `Channel.workspace_id` is renamed, every `/ask` and ai-config call 404s or 500s (the `select(Channel.workspace_id)` queries break). |
| `File` | `filesystem.model` | (indirectly, via `processing/`, not `src/rag/` directly) | `src/processing/images.py:10`, `src/processing/tasks.py:10` | `File.chunk_count`/`processing_error` writes are noted as **silently dropped** because those columns don't exist yet on `File` (`docs/chat-memory-handoff.md`, "Filesystem owner" integration finding) — a pre-existing gap, not something RAG code guards against. |
| `MinIOFileSystem` | `filesystem.storage.minio` | reading uploaded files for ingestion | `src/processing/tasks.py:11` | If `split_path`'s workspace-scoping changes, ingestion could read/write outside the intended workspace prefix. |
| `AsyncSessionLocal`, `SessionLocal`, `Base`, `engine` | `database` | every RAG DB access (see the SQLAlchemy section in file 06) | `rag/router.py:30,173`, `rag/ai_settings.py:19`, `rag/settings_router.py:13,25,42` | Renaming `SessionLocal`/`AsyncSessionLocal` breaks every RAG DB call site simultaneously — there is no RAG-owned session factory. |
| `SessionDep` | `auth.utils.session` | `/ask`'s auth dependency, supplying `session.sub` (user id) | `rag/router.py:27`, used at `:146,163` | If `SessionDep`'s `.sub` attribute is renamed, `_persist_exchange`'s `sender_id=user_id` breaks. |

### Self-test Q&A
- **Q: `rag/router.py:127` imports `sio` with a comment "import-only, never
  modified" — what does that comment actually promise, and to whom?**
  A: It's a boundary marker for the RAG-owning contributor: `chat/realtime.py` is
  teammate-owned code (see `docs/superpowers/plans/2026-07-02-ask-hardening-and-smart-context.md`'s
  Global Constraints: "Never modify teammate-owned files ... Importing from them is
  fine") — the comment documents that this import is a read-only dependency, not a
  hidden edit.
- **Q: If `chat.model.Message` gained a new required constructor field tomorrow, which
  two exact call sites in RAG code would need updating?**
  A: `_persist_exchange`'s two `Message(...)` constructions (`rag/router.py:109-112`) —
  the question row and the assistant row.
- **Q: Why does RAG code import `Channel` from `workspace.model` instead of assuming a
  `channel_id → workspace_id` helper exists on `workspace`'s public API?**
  A: There isn't one exposed — `workspace/__init__.py` only exports `is_owner,
  require_perms, WorkspaceID, RoleID` (`workspace/__init__.py:1,3`); RAG code queries
  the ORM model directly instead.

---

## 3. Events & tables: contracts other code must honor

**`ai_message` Socket.IO event — payload contract, consumer = frontend (not present in
this working tree).**
```python
await sio.emit("ai_message", {
    "channel_id": str(channel_id),
    "question_message_id": str(question_id),
    "message_id": str(answer_id),
    "question": question,
    "content": answer,
    "role": "assistant",
    "request_id": request_id,          # uuid7, minted per /ask — the correlation key (→ 00 §13)
}, room=f"channel:{channel_id}")   # Socket.IO room convention, → 00 §13
```
This is deliberately **not** the chat module's `message` event/`MessageSchema` — see
`router.py:124-125`'s comment: `MessageSchema.sender_id` is non-optional but assistant
rows have `sender_id = NULL`. Confirmed: `grep -rl "ai_message\|ai/config\|askAi"
frontend/src` in this working tree returns **no hits** — the frontend's consumer for
this event does not exist in this checkout (only referenced in
`docs/chat-memory-handoff.md`'s "Frontend owner" note as "working `@ai` reference
exists" on a different, unmerged worktree/branch). Anyone building the frontend
consumer in *this* tree is starting from zero, not from existing partial code.

**`messages.indexed_at` — RAG-owned column on a teammate-owned table.**
`Message.indexed_at: Mapped[datetime | None]` (`chat/model.py:54`), added by this
feature with the comment "Added for the chat-memory-indexing feature (partitions the
un-indexed tail injected as context from the indexed body recalled via retrieval)"
(`:52-53`). Three consumers: the indexer sets it (`processing/chat_indexing.py:168`,
`m.indexed_at = stamped`), the tail loader filters on it being `NULL`
(`rag/router.py:77`), and the indexer's own query selects `WHERE indexed_at IS NULL`
(`processing/chat_indexing.py:149`). **Ownership note:** this column lives on
`chat/model.py`, a teammate-owned file, but its semantics and every reader/writer are
RAG code — it's the one field RAG code was allowed to add to `Message` per the
hardening plan's constraints.

**`ai_settings` table — fully RAG-owned.** Defined in `rag/ai_settings.py:34-49`
(`class AiSettings(Base)`), with a composite `UniqueConstraint("workspace_id",
"channel_id")` plus a partial unique index for the workspace-default row
(`channel_id IS NULL`) — see `ai_settings.py:38-42`'s comment explaining why a plain
unique constraint can't guard the default row (Postgres treats NULLs as distinct).

**Milvus `talos_documents` — shared collection, source-field discipline, and the
concrete leak risk.** Both file chunks and chat-memory segments live in the same
collection (`WORKSPACE_COLLECTION`, `vector_store.py:69`) — the dynamic-schema,
metadata-filtered design from 00 §3, and the convention-not-schema source discipline it
depends on (→ 00 §3). The only thing partitioning
them is every caller's own `source == "file"` / `source == "chat"` expr conjunct (see
file 06's Milvus section). **Confirmed cross-branch leak risk, not yet landed on this
tree:** `docs/audits/2026-07-02-deep-audit-findings.md`: "`origin/search`:
`source=="chat"` vectors will leak into its file search unless its Milvus expr filters
source." The handoff doc names the exact fix: "when it lands, patch
`filesystem.service.search_files`'s Milvus expr to include `source == \"file\"`." This
working tree's `src/filesystem/service.py` has **no Milvus/retriever code in it at
all** (`grep -n "get_retriever\|build_rag_pipeline\|Milvus\|expr"
src/filesystem/service.py` — zero hits) — confirming the `search` branch
(`remotes/origin/search`, not merged into `feature/chat-message-memory`, verified via
`git merge-base --is-ancestor origin/search HEAD` → not an ancestor) has not landed
here. The fix described in the audit doc cannot be verified against this repo's current
`filesystem/service.py` because the code it would patch doesn't exist in this tree yet.

### Self-test Q&A
- **Q: A new teammate branch adds file search over Milvus but forgets the
  `source == "file"` filter. What's the concrete symptom?**
  A: Chat-memory segment vectors (private conversation content) show up as "file search"
  hits — a content-leak, not a crash, so it could ship unnoticed without the eval doc's
  explicit callout.
- **Q: Why is `messages.indexed_at` added to `chat/model.py` instead of a RAG-owned
  side table keyed on `message_id`?**
  A: Not explicitly justified in the code, but the two-tier `/ask` model
  (`router.py:6-11`) needs a single fast `WHERE indexed_at IS NULL` filter per channel
  ordered by `sent_at` — a side table would need a join on every tail load. The column
  is intentionally minimal (nullable, single field) to keep the teammate-file touch
  small.
- **Q: If you rename `ai_settings.overrides` to `ai_settings.patch`, what three files
  need updating?**
  A: `rag/ai_settings.py` (the column def and every `AiSettings.overrides` reference in
  `resolve_ai_config`), `rag/settings_router.py` (`row.overrides` reads/writes in
  `_view`/`_apply_patch`), and any existing Postgres data (no Alembic — a rename needs a
  manual migration or DB recreate per the "No Alembic" caveat).

---

## 4. Permission strings reused

Permission strings are free-form dotted strings (`resource.subresource:action`),
parsed via `ScopedPermission.from_str(...)` (`src/permissions/model.py`) — **there is no
centralized enum of permission constants**; every router just writes the string
literal. RAG code reuses:

| string | defined/established by | used by RAG at |
|---|---|---|
| `"workspace:view"` | `workspace/router.py:14` (base dependency) | `rag/settings_router.py:79` (`GET /ai/config` at workspace scope) |
| `"channel:view"` | `workspace/router.py:18` (base dependency) | `rag/settings_router.py:98` (`GET /ai/config` at channel scope) |
| `"channel.message:send"` | first declared for chat message-send at `chat/router.py:28` (`POST /messages`) | reused verbatim by `/ask` (`rag/router.py:145`) — the router docstring explains why: "this adds channel.message:send" on top of the channel-level view perms already applied by mounting (`router.py:5`) |
| `"workspace.role:manage"` | `permissions/router.py` (role-management endpoints, e.g. `:87,138,174,222,251,286,322,380`) | reused by both ai-config `PATCH` endpoints (`rag/settings_router.py:84,104`) — i.e. changing AI config requires the same permission as managing workspace roles, not a dedicated "manage AI config" permission |

**Consequence of the strings being un-enumerated:** a typo in a permission string (e.g.
`"channel.mesage:send"`) would not be caught by any type checker — it would just always
deny (or, depending on `require_perms`'s matching semantics, potentially always allow if
matched loosely). This repo has no test asserting the RAG permission strings exactly
match the chat module's canonical strings; they're kept in sync by convention and code
comments only.

### Self-test Q&A
- **Q: Why does patching workspace-level AI config require `workspace.role:manage`
  instead of a dedicated permission?**
  A: No dedicated "manage AI config" permission was ever defined — `settings_router.py`
  reuses the existing role-management permission as the closest available admin-tier
  gate (`settings_router.py:84,104`).
- **Q: `/ask` requires `channel.message:send`. Where was that exact string first
  established, and why does `/ask` reuse it rather than defining `ai.ask:send` or
  similar?**
  A: `chat/router.py:28`, for the ordinary "post a chat message" endpoint. The `/ask`
  docstring frames `/ask` as an extension of message-sending semantics — asking the AI a
  question is treated as a form of sending a message to the channel (`router.py:1-5`).
- **Q: If `permissions/model.py`'s `ScopedPermission.from_str` parsing rules ever
  change (e.g. required a different separator), which RAG files would need a matching
  string-literal edit?**
  A: `rag/router.py:145`, `rag/settings_router.py:79,84,98,104` — every
  `require(...)`/`require_perms(...)` call site with a literal string.

---

## 5. Cross-branch coordination state

**rich-msg (`origin/rich-msg`, not merged here): `Message.content: str → JSONB`
(ProseMirror), and the one unresolved write seam.** `rag/message_text.py` is the single
seam we built for this: `message_text(message) -> str` extracts plain text from either
today's `str` content or rich-msg's future ProseMirror `dict`
(`message_text.py:1-32`, handling `text`/`mention`/`doc` node types at `:12-21`). Both
**read** sites already route through it: `processing/chat_indexing.py` (per the
2026-07-02 plan Task 2, `build_chat_documents`) and `rag/router.py`'s
`_load_unindexed_tail` (`:88-89`, `message_text(m)` calls). The **one remaining
unconverted touchpoint is `_persist_exchange`** (`rag/router.py:109-112`), which still
does `Message(..., content=question, ...)` and `Message(..., content=answer, ...)` —
plain-string writes. `docs/audits/2026-07-02-deep-audit-findings.md` names the exact
consequence: "plain-str content will violate `content_size_bytes NOT NULL`" once
rich-msg's schema lands, and the fix direction: switch to rich-msg's
`wrap_plain_text(...)`/`set_content()` helper instead of assigning a raw string. This is
explicitly **not yet done** — it's a known TODO, not a landed fix, confirmed by reading
the current `_persist_exchange` body.

**search (`origin/search`, not merged here): `get_retriever` no longer exists,
source-filter leak.** Per `docs/chat-memory-handoff.md`'s "Search owner (nourhane)"
note: `filesystem/service.py:375` (on the `search` branch, not this tree) imports
`get_retriever`, a function that was replaced by `build_rag_pipeline`
(`rag/retrieval/retrievers.py:35`) during the 2026-07-01 hardening plan — that import
would fail or (per the note) silently return empty results through a broad
`except`. **Not verifiable against this working tree**: `src/filesystem/service.py`
here has zero Milvus-related code (confirmed by grep, see §3) — the `search` branch's
actual current state cannot be inspected from this checkout; only the coordination
note's description is available.

**mcp-server (`origin/mcp-server`, not merged here): depends on the pre-split
`RAGChain(...).query()` call shape.** `docs/chat-memory-handoff.md`'s "MCP owner
(MohabG2)" note: "rebase onto origin/main (branch reverts the model→database rename);
`RAGChain(collection_name=, workspace_id=, file_ids=)` + `.query()` is unchanged and
compatible." This is corroborated by the hardening plan's explicit design goal for
Task 3: "`RAGChain.stream_query(...)` / `RAGChain.query(...)` keep their exact current
signatures (thin wrappers) ... so ... the mcp-server branch's call shape are untouched"
(`docs/superpowers/plans/2026-07-02-ask-hardening-and-smart-context.md`, Task 3
Interfaces). **Not present in this tree**: `git merge-base --is-ancestor origin/mcp-server
HEAD` returns false — there is no `mcp-server` code to inspect here; this is a
forward-compatibility guarantee we uphold from this side only (keep `.query()`'s
signature stable), not something testable in this checkout.

**frontend: no ai-config client exists in this working tree.** The handoff doc's
"Frontend owner" note describes a desired end-state ("the AI-config client should
target the nested endpoints `GET/PATCH /api/workspaces/{id}/ai/config` and
`/api/channels/{id}/ai/config` (replacing the flat `/api/ai/config` scaffold)") and
references "a working `@ai` reference" with "ChatPage/askAi/onAiMessage demo patches" —
but as confirmed in §3, `grep -rln "ai/config\|ai-config\|askAi\|ai_message"
frontend/src` in this checked-out `frontend/` directory returns **no matches**. The flat
`/api/ai/config` scaffold the note warns against replacing is not present either — there
is currently **no** frontend AI-config client of any shape in this working tree. Anyone
implementing it here should target `rag/settings_router.py`'s actual current endpoints
directly: `GET/PATCH /api/workspaces/{workspace_id}/ai/config`
(`settings_router.py:79,84`) and `GET/PATCH /api/channels/{channel_id}/ai/config`
(`:98,104`) — there is no flat scaffold to migrate away from in this tree, just a clean
slate.

**Suggested merge order** (from `docs/chat-memory-handoff.md`, last line): mcp-server
rebase → chat-message-memory → rich-msg → search → frontend. This ordering is a plan
artifact, not something enforced by code — worth re-checking against current remote
branch state before actually merging anything.

### `if teammate X changes Y, you must Z`

| teammate / branch | if they change... | you must... |
|---|---|---|
| chat (kiro) | `Message.content` from `str` to JSONB (rich-msg merge) | rewrite `_persist_exchange`'s two `Message(...)` constructions (`rag/router.py:109-112`) to use rich-msg's `set_content()`/`wrap_plain_text()` instead of `content=<str>`, or writes will violate `content_size_bytes NOT NULL` |
| chat (kiro) | `MessageRole` enum members/names | re-check `_load_unindexed_tail`'s `m.role != MessageRole.SYSTEM` filter (`router.py:78`) and the `AIMessage`/`HumanMessage` branch on `MessageRole.ASSISTANT` (`:88-89`) |
| chat (kiro) | `chat.realtime.sio`'s room-naming convention | update `_broadcast_ai_message`'s `room=f"channel:{channel_id}"` (`router.py:139`) to match, or the AI answer stops reaching connected clients (silently — the emit is wrapped in try/except) |
| workspace | `require_perms`'s signature or `Channel.workspace_id` column | fix every `require(...)` call in `rag/router.py`/`rag/settings_router.py` and every `select(Channel.workspace_id)` query (`router.py:154-155`, `settings_router.py:92`) |
| database | `SessionLocal`/`AsyncSessionLocal`/`Base` names or `Base.metadata.create_all` semantics | every RAG DB call site breaks simultaneously; also re-verify the transitive `AiSettings` registration path described in §1 still runs before `create_all` |
| search (nourhane) | lands `filesystem.service.search_files` without a `source == "file"` Milvus expr conjunct | patch their expr yourself (or flag it in review) before merge — chat-memory content will otherwise leak into file-search results |
| mcp-server (MohabG2) | calls anything on `RAGChain` beyond `__init__(collection_name=, workspace_id=, file_ids=)` + `.query()` | you've broken the compatibility contract Task 3 of the hardening plan explicitly preserved — check `rag_chain.py:222-226,30-47` still match before merging |
| frontend | ships an ai-config client | point it at the real nested endpoints (`settings_router.py:79,84,98,104`); there is no flat `/api/ai/config` scaffold in this tree to migrate away from — this is greenfield here |
| rich-msg | ships `set_content()`/`wrap_plain_text()` helpers | wire `_persist_exchange` (`router.py:109-112`) to them; `message_text()` (`message_text.py:24-32`) already handles the read side for both shapes, no change needed there |

### Self-test Q&A
- **Q: Of the three rich-msg touchpoints in RAG-adjacent code, which one is still
  unconverted, and what specifically breaks if rich-msg lands before it's fixed?**
  A: `_persist_exchange` (`rag/router.py:109-112`) still writes `content=<str>` directly;
  once `Message.content` becomes a JSONB ProseMirror doc, this raw string write violates
  the `content_size_bytes NOT NULL` constraint rich-msg introduces (per
  `docs/audits/2026-07-02-deep-audit-findings.md`).
- **Q: You're asked to verify the `search` branch's Milvus leak fix is in place. Can you
  do that by reading files in this working tree?**
  A: No — `src/filesystem/service.py` in this tree has no Milvus code at all (confirmed
  by grep in §3); the `search` branch isn't merged here (`git merge-base
  --is-ancestor origin/search HEAD` is false). You'd need to check out or fetch that
  branch specifically.
- **Q: Does anything in this repo currently call `/api/workspaces/{id}/ai/config`
  from the frontend?**
  A: No — confirmed by grep; there's no ai-config client in `frontend/src` in this
  checkout at all, flat or nested.
- **Q: Why does the hardening plan go out of its way to keep `RAGChain.query()`'s exact
  signature, when the internal implementation was fully restructured
  (`prepare()`/`stream_answer()` split)?**
  A: Because `mcp-server` (a branch not merged here) depends on that exact call shape;
  preserving the public wrapper lets the internal architecture change without
  coordinating a simultaneous change on a branch we don't control from this checkout.

