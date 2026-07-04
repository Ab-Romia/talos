# /ask Hardening + Smart Chat Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/ask` async-correct and failure-safe, make the chat indexer concurrency-safe, upgrade chat memory from per-message vectors to topic segments with decay+redundancy re-ranking, broadcast AI answers over the existing Socket.IO channel, and clean out dead config.

**Architecture:** All changes live in RAG-owned code (`src/rag/`, `src/processing/`, `src/config/config.py`, `tests/`). `RAGChain` is split into an eager `prepare()` (retrieval, runs in a thread, errors before HTTP headers) and a `stream_answer()` generator (LLM tokens, iterated via threadpool). The router persists the question+answer atomically *after* a successful stream and then emits one `ai_message` Socket.IO event to the channel room. The indexer takes a Postgres advisory lock, drains multiple batches per tick, and embeds inactivity-gap segments instead of single messages. Chat recall fetches a wider candidate pool and re-ranks with time-decay + lexical-redundancy suppression.

**Tech Stack:** Python 3.14, FastAPI/Starlette, LangChain + Milvus (`langchain_milvus`), taskiq + Redis streams, python-socketio, SQLAlchemy (sync + async), pytest.

## Global Constraints

- **Never modify teammate-owned files**: `src/chat/`, `src/workspace/`, `src/auth/`, `src/filesystem/`, `src/app.py`, `docker-compose.yaml`, `src/database.py`, `src/permissions/`, `src/notifications/`. Importing from them is fine.
- **Branch**: `feature/chat-message-memory`. Never commit to `main`.
- **Commits**: author `Ab-Romia <aabouroumia@gmail.com>`. NO AI attribution, NO `Co-Authored-By` lines, ever.
- **Run tests**: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q` from the repo root (`/home/romia/talos-main`). Requires the test DB: `docker compose up -d postgres-test`. Do NOT use bare `uv run pytest` (hits a stale global binary). PYTHONPATH=src is set automatically by pyproject for pytest.
- **Baseline before Task 1**: the suite passes 44/44 on `tests/rag tests/chat`. It must pass after every task.
- **Config chokepoint**: every new knob is a field on `RagConfig` in `src/config/config.py` (env var = uppercased field name). No other config mechanism.
- The 3 uncommitted TODO comments in the working tree (`src/chat/model.py`, `src/chat/realtime.py`, `src/rag/router.py`) are the owner's personal markers. Leave the two in `src/chat/*` untouched. The one in `src/rag/router.py` (`# TODO: Checking the file ids permissions prior`) stays as-is (out of scope).

---

### Task 1: Dead-code & dead-config cleanup

**Files:**
- Modify: `src/config/config.py` (remove `yaml_file`, `conversation_memory_k`)
- Modify: `src/config/prompts.py` (remove `RAG_PROMPT_WITHOUT_MEMORY`)
- Modify: `src/rag/generation.py` (remove `get_memory`, `NullHistory`)
- Modify: `src/rag/rag_chain.py` (remove all `self.memory` usage)
- Modify: `src/rag/retrieval/query_processing.py` (remove `get_multiquery_retriever`)
- Modify: `src/rag/__init__.py` (drop removed exports)
- Modify: `src/rag/vector_store.py` (fix stale `get_workspace_vectorstore` docstring)
- Delete: `config/rag_config.example.yaml`, `config/prompts/hyde_prompt.yaml`, `config/prompts/qa_prompt.yaml`, `config/prompts/query_rewrite_prompt.yaml`
- Modify: `tests/rag/test_rag_chain.py` (delete the memory test)

**Interfaces:**
- Produces: `RAGChain` with NO `self.memory` attribute; `chat_history` prompt slot fed only by `self._injected_history`. Later tasks build on this cleaned class.

- [ ] **Step 1: Delete dead files**

```bash
git rm config/rag_config.example.yaml config/prompts/hyde_prompt.yaml config/prompts/qa_prompt.yaml config/prompts/query_rewrite_prompt.yaml
```

- [ ] **Step 2: Remove dead config fields**

In `src/config/config.py`:
- Delete the line `yaml_file: Path = Path("config/rag_config.yaml")` and the now-unused `from pathlib import Path` import.
- Delete the line `conversation_memory_k: int = 3` and its comment if any.

- [ ] **Step 3: Remove `RAG_PROMPT_WITHOUT_MEMORY`**

In `src/config/prompts.py`, delete the whole `RAG_PROMPT_WITHOUT_MEMORY = ChatPromptTemplate.from_messages(...)` block (starts line 35). Check `src/config/__init__.py` and remove it from any export list there. Note `tests/rag/test_eval_uses_production_path.py:37` asserts this name is ABSENT from eval source — that test keeps passing.

- [ ] **Step 4: Remove `get_memory`/`NullHistory` from generation**

In `src/rag/generation.py`: change `__all__ = ["get_llm", "get_memory"]` to `__all__ = ["get_llm"]`; delete the `get_memory` function (lines ~43-53) and the `NullHistory` class it returns, plus any now-unused imports (`BaseChatMessageHistory`, `InMemoryChatMessageHistory`).

- [ ] **Step 5: Remove memory from RAGChain**

In `src/rag/rag_chain.py`:
- Remove `get_memory` from the `from rag import (...)` block (line 46).
- Delete `self.memory = get_memory(use_memory=config.conversation_memory_k > 0)` (line 113).
- Change the chat_history lambda (lines 120-122) to:
```python
"chat_history": RunnableLambda(
    lambda _: list(self._injected_history)
),
```
- In `stream_query` change `history_at_prompt = self._injected_history + list(self.memory.messages)` (line 220) to `history_at_prompt = list(self._injected_history)`.
- Delete the two trailing lines (241-242): `self.memory.add_user_message(question)` / `self.memory.add_ai_message(full_response)` and the comment above them.

In `src/rag/__init__.py`: remove `get_memory` from imports/`__all__` if present.

- [ ] **Step 6: Remove `get_multiquery_retriever`**

In `src/rag/retrieval/query_processing.py`: delete the function (line 41+), remove it from `__all__` (line 15), remove now-unused imports (`MultiQueryRetriever`, `BaseRetriever` if unused). Remove it from `src/rag/__init__.py`/`src/rag/retrieval/__init__.py` exports if present.

- [ ] **Step 7: Fix stale docstring**

In `src/rag/vector_store.py`, `get_workspace_vectorstore` docstring (~line 160) claims it establishes the pymilvus ORM connection first — it doesn't. Replace that sentence with: `Relies on the module-level MilvusClient ORM bridge (see _install_milvus_client_orm_bridge) for the pymilvus ORM connection.`

- [ ] **Step 8: Update tests**

In `tests/rag/test_rag_chain.py`: delete `test_turn_recorded_after_generation` entirely (memory is gone). Leave the other tests untouched.

- [ ] **Step 9: Run the suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q`
Expected: all pass (one fewer test than baseline). Also run `grep -rn "conversation_memory_k\|get_memory\|yaml_file\|RAG_PROMPT_WITHOUT_MEMORY\|get_multiquery_retriever" src/ --include=*.py` — expected: no hits.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "chore(rag): delete dead config and dead in-process memory path"
```

---

### Task 2: `message_text()` — rich-msg-ready content access

**Files:**
- Create: `src/rag/message_text.py`
- Modify: `src/processing/chat_indexing.py` (use it in `build_chat_documents`)
- Modify: `src/rag/router.py:77-81` (use it in `_load_unindexed_tail`)
- Test: `tests/rag/test_message_text.py`

**Interfaces:**
- Produces: `message_text(message) -> str` — the ONE place that turns `Message.content` into plain text. Handles today's `str` and the incoming `rich-msg` branch's ProseMirror `dict` (extracts concatenated text nodes). Every later task that reads message content uses this.

- [ ] **Step 1: Write the failing tests**

```python
# tests/rag/test_message_text.py
"""message_text() is the single seam for Message.content -> str, so the
rich-msg branch (content: str -> ProseMirror JSONB dict) breaks nothing."""
from types import SimpleNamespace

from rag.message_text import message_text


def test_plain_string_content_passthrough():
    assert message_text(SimpleNamespace(content="hello world")) == "hello world"

def test_none_content_is_empty():
    assert message_text(SimpleNamespace(content=None)) == ""

def test_prosemirror_doc_extracts_text():
    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "hello "},
            {"type": "mention", "attrs": {"id": "u1", "label": "kiro"}},
        ]},
        {"type": "paragraph", "content": [{"type": "text", "text": "second line"}]},
    ]}
    assert message_text(SimpleNamespace(content=doc)) == "hello @kiro\nsecond line"
```

- [ ] **Step 2: Run to verify failure**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_message_text.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'rag.message_text'`

- [ ] **Step 3: Implement**

```python
# src/rag/message_text.py
"""Single seam turning Message.content into plain text.

Today content is a plain str. The rich-msg branch converts it to a
ProseMirror JSONB document; this helper already extracts text from that
shape, so when rich-msg lands only this file needs review, not every
indexer/router call site.
"""

__all__ = ["message_text"]


def _node_text(node: dict) -> str:
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    if t == "mention":
        label = (node.get("attrs") or {}).get("label", "")
        return f"@{label}" if label else ""
    children = node.get("content") or []
    sep = "\n" if t == "doc" else ""
    return sep.join(_node_text(c) for c in children)


def message_text(message) -> str:
    content = getattr(message, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _node_text(content)
    return str(content)
```

- [ ] **Step 4: Run to verify pass**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_message_text.py -q`
Expected: 3 passed

- [ ] **Step 5: Use it at both read call sites**

In `src/processing/chat_indexing.py`, add `from rag.message_text import message_text` and in `build_chat_documents` change `text = f"{_role_str(m.role)}: {m.content}"` to `text = f"{_role_str(m.role)}: {message_text(m)}"`.

In `src/rag/router.py`, add `from .message_text import message_text` and in `_load_unindexed_tail` change the loop body to:
```python
    for m in reversed(rows):  # oldest -> newest
        history.append(
            AIMessage(content=message_text(m)) if m.role == MessageRole.ASSISTANT
            else HumanMessage(content=message_text(m))
        )
```
(`_persist_assistant_turn` WRITES content and cannot be future-proofed without rich-msg's `set_content()` API — Task 9 documents that in the handoff doc instead.)

- [ ] **Step 6: Run full suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/rag/message_text.py tests/rag/test_message_text.py src/processing/chat_indexing.py src/rag/router.py
git commit -m "feat(rag): centralize Message.content->text in message_text (rich-msg ready)"
```

---

### Task 3: Split RAGChain into `prepare()` + `stream_answer()`

**Files:**
- Modify: `src/rag/rag_chain.py`
- Test: `tests/rag/test_rag_chain.py` (add tests; existing ones keep passing)

**Interfaces:**
- Consumes: Task 1's cleaned RAGChain (no memory).
- Produces:
  - `PreparedAsk` dataclass: `question: str`, `context: str`, `history: list` (in `src/rag/rag_chain.py`, exported).
  - `RAGChain.prepare(question: str) -> PreparedAsk` — SYNC; does rewrite/HyDE/retrieval/context formatting; raises on Milvus/LLM-rewrite failure.
  - `RAGChain.stream_answer(prepared: PreparedAsk, include_citations: bool = True)` — SYNC generator of str chunks; fills `self.trace` after generation.
  - `RAGChain.stream_query(...)` / `RAGChain.query(...)` keep their exact current signatures (thin wrappers), so eval (`tests/rag_evaluation/eval_utils.py`), `scripts/debug_ask.py`, and the mcp-server branch's call shape are untouched.

- [ ] **Step 1: Write the failing tests** (append to `tests/rag/test_rag_chain.py`)

```python
def test_prepare_then_stream_answer_matches_stream_query():
    """prepare() does retrieval eagerly; stream_answer() only generates."""
    captured = {}
    chain = _make_chain(captured, chat_history=[HumanMessage("earlier")])
    prepared = chain.prepare("LIVE_Q")
    assert prepared.question == "LIVE_Q"
    assert "context chunk" in prepared.context      # retrieval already happened
    assert [m.content for m in prepared.history] == ["earlier"]
    out = "".join(chain.stream_answer(prepared, include_citations=False))
    assert out == "the answer"
    assert chain.trace.original_query == "LIVE_Q"   # trace filled by stream_answer

def test_prepare_raises_on_retriever_failure():
    """Retrieval errors surface from prepare(), NOT mid-stream."""
    class _Boom:
        def invoke(self, _q):
            raise RuntimeError("milvus down")
    captured = {}
    chain = _make_chain(captured)
    chain.retriever = _Boom()
    import pytest
    with pytest.raises(RuntimeError, match="milvus down"):
        chain.prepare("q")

def test_stream_query_still_works_as_wrapper():
    captured = {}
    chain = _make_chain(captured)
    out = "".join(chain.stream_query("q", include_citations=False))
    assert out == "the answer"
```

- [ ] **Step 2: Run to verify failure**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_rag_chain.py -q`
Expected: new tests FAIL (`AttributeError: 'RAGChain' object has no attribute 'prepare'`); old ones pass.

- [ ] **Step 3: Implement the split**

In `src/rag/rag_chain.py`:

Add near the top (after imports):
```python
from dataclasses import dataclass, field


@dataclass
class PreparedAsk:
    """Everything retrieval produced, ready for generation."""
    question: str
    context: str
    history: list = field(default_factory=list)
```
and extend `__all__ = ["RAGChain", "PreparedAsk"]`.

Replace `stream_query` (and keep the existing `self.chain` construction DELETED — the RunnableParallel block, lines 114-128, is no longer needed) with:

```python
    def prepare(self, question: str) -> PreparedAsk:
        """Run the retrieval half eagerly: rewrite -> retrieve (files + chat)
        -> format context. Raises on failure, which lets the HTTP layer turn
        Milvus/LLM-rewrite errors into a real error response BEFORE any
        response headers are sent."""
        self.last_query_info = {
            "original_query": question,
            "rewritten_query": None,
            "generated_queries": [],
            "retrieved_docs": [],
            "num_docs_retrieved": 0,
        }
        docs = self._rewrite_and_retrieve(question)
        context = self._format_docs(docs)
        self.last_query_info["retrieved_docs"] = self.retrieved_docs
        self.last_query_info["num_docs_retrieved"] = len(self.retrieved_docs)
        return PreparedAsk(
            question=question,
            context=context,
            history=list(self._injected_history),
        )

    def stream_answer(self, prepared: PreparedAsk, include_citations: bool = True):
        """Generation half: stream LLM tokens for an already-prepared ask.
        Fills self.trace after the answer completes."""
        from rag import format_citations

        prompt_value = RAG_PROMPT.invoke({
            "context": prepared.context,
            "question": prepared.question,
            "chat_history": prepared.history,
        })
        for chunk in (self.llm | StrOutputParser()).stream(prompt_value):
            yield chunk

        self._fill_trace(prepared.question, prepared.history)

        if include_citations:
            yield "\n\nSources:"
            for citation in format_citations(self.retrieved_docs):
                yield f"\n{citation}"

    def stream_query(self, question: str, include_citations: bool = True):
        """Back-compat wrapper: prepare + stream in one sync generator (used by
        query(), the eval harness, and scripts/debug_ask.py)."""
        prepared = self.prepare(question)
        yield from self.stream_answer(prepared, include_citations)
```

Keep `query()` as-is (it consumes `stream_query`). Remove the now-unused imports `RunnablePassthrough`, `RunnableParallel` (keep `RunnableLambda` only if still used — it isn't after this change; remove it too).

- [ ] **Step 4: Run the suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q`
Expected: all pass. The pre-existing `_make_chain` fake LLM receives a `ChatPromptValue` (from `RAG_PROMPT.invoke`), and its `.to_messages()` call keeps working.

- [ ] **Step 5: Commit**

```bash
git add src/rag/rag_chain.py tests/rag/test_rag_chain.py
git commit -m "refactor(rag): split RAGChain into eager prepare() and stream_answer()"
```

---

### Task 4: Async-correct `/ask` with real errors and post-stream persistence

**Files:**
- Modify: `src/rag/router.py` (rewrite the endpoint body)
- Test: `tests/rag/test_ask_endpoint.py` (new — first tests for the HTTP surface)

**Interfaces:**
- Consumes: `RAGChain.prepare` / `RAGChain.stream_answer` (Task 3), `message_text` (Task 2).
- Produces:
  - `POST /api/channels/{channel_id}/ask` behavior contract: 404 unknown channel; **502 JSON error if retrieval/prepare fails (before streaming)**; 200 streaming answer; on mid-generation failure the stream ends with the marker `\n\n[ask:error]` and NOTHING is persisted; on success the user question AND assistant answer are committed together AFTER the stream; on client disconnect nothing is persisted (deliberate: an exchange is only recorded when the answer was delivered).
  - `_persist_exchange(channel_id, user_id, question, asked_at, answer) -> tuple[UUID, UUID]` (question_id, answer_id) — Task 5 calls its return values.
  - `_ERROR_MARKER = "\n\n[ask:error]"` module constant.

- [ ] **Step 1: Write the failing tests**

```python
# tests/rag/test_ask_endpoint.py
"""First tests for the /ask HTTP surface. RAGChain is monkeypatched so no
Milvus/LLM is touched; fixtures (client, test_channel, auth_token, path) come
from tests/conftest.py."""
import json

import pytest

from chat.router import get_channel_messages
from rag.router import ask_question
from rag.trace import RagTrace


class _FakeChain:
    fail_prepare = False
    fail_stream = False
    last = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.trace = RagTrace()
        type(self).last = self

    def prepare(self, question):
        if type(self).fail_prepare:
            raise RuntimeError("milvus down")
        return question

    def stream_answer(self, prepared, include_citations=True):
        yield "hello "
        if type(self).fail_stream:
            raise RuntimeError("llm exploded")
        yield "world"
        if include_citations:
            yield "\n\nSources:"
            yield "\n- doc.pdf"


@pytest.fixture(autouse=True)
def fake_chain(monkeypatch):
    _FakeChain.fail_prepare = False
    _FakeChain.fail_stream = False
    monkeypatch.setattr("rag.router.RAGChain", _FakeChain)
    return _FakeChain


def _ask(client, path, channel, token, **body):
    return client.post(
        path(ask_question, channel_id=channel.id),
        json={"question": "q?", **body},
        headers={"Authorization": f"Bearer {token}"},
    )


def _messages(client, path, channel, token):
    r = client.get(path(get_channel_messages, channel_id=channel.id),
                   headers={"Authorization": f"Bearer {token}"})
    return r.json()


def test_ask_streams_and_persists_exchange(client, test_channel, auth_token, path):
    r = _ask(client, path, test_channel, auth_token, include_citations=False)
    assert r.status_code == 200
    assert r.text == "hello world"
    roles = [(m["role"], m["content"]) for m in _messages(client, path, test_channel, auth_token)]
    # question + answer both persisted, answer excludes citation footer
    assert ("user", "q?") in [(str(role).lower(), c) for role, c in roles]
    assert any("hello world" == c for _, c in roles)


def test_ask_prepare_failure_is_502_and_persists_nothing(client, test_channel, auth_token, path, fake_chain):
    fake_chain.fail_prepare = True
    r = _ask(client, path, test_channel, auth_token)
    assert r.status_code == 502
    assert _messages(client, path, test_channel, auth_token) == []


def test_ask_midstream_failure_marks_stream_and_persists_nothing(client, test_channel, auth_token, path, fake_chain):
    fake_chain.fail_stream = True
    r = _ask(client, path, test_channel, auth_token, include_citations=False)
    assert r.status_code == 200          # headers were already sent
    assert r.text.startswith("hello ")
    assert "[ask:error]" in r.text       # client can detect the failure
    assert _messages(client, path, test_channel, auth_token) == []


def test_ask_debug_appends_trace_payload(client, test_channel, auth_token, path):
    r = _ask(client, path, test_channel, auth_token, include_citations=False, debug=True)
    body, _, dbg = r.text.partition("__ASK_DEBUG__")
    assert "hello world" in body
    payload = json.loads(dbg)
    assert "model" in payload and "chat_candidates" in payload


def test_ask_citation_footer_stripped_from_persisted_answer(client, test_channel, auth_token, path):
    r = _ask(client, path, test_channel, auth_token, include_citations=True)
    assert "Sources:" in r.text
    contents = [m["content"] for m in _messages(client, path, test_channel, auth_token)]
    assert "hello world" in contents
    assert not any("Sources:" in c for c in contents)
```

- [ ] **Step 2: Run to verify failure**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_ask_endpoint.py -q`
Expected: FAIL (current endpoint calls `chain.stream_query`, persists question up-front, no 502 path, no error marker).

- [ ] **Step 3: Rewrite the endpoint**

In `src/rag/router.py`:

Replace the `_persist_assistant_turn` helper with:
```python
async def _persist_exchange(channel_id: UUID, user_id: UUID, question: str,
                            asked_at, answer: str) -> tuple[UUID, UUID]:
    """Persist the question + answer together, AFTER a successful stream.
    An exchange is only recorded when the answer was actually delivered:
    a mid-stream failure or client disconnect persists nothing, so the tail
    never grows dangling human turns. asked_at (captured at request start)
    keeps the question ordered before the answer. Uses the ORM directly
    because MessageSchema requires a non-null sender_id (assistant rows
    have sender_id NULL)."""
    async with AsyncSessionLocal() as db:
        q = Message(channel_id=channel_id, sender_id=user_id,
                    content=question, role=MessageRole.USER, sent_at=asked_at)
        a = Message(channel_id=channel_id, sender_id=None,
                    content=answer, role=MessageRole.ASSISTANT)
        db.add(q)
        db.add(a)
        await db.commit()
        return q.id, a.id
```

Add the marker constant next to the existing ones:
```python
# Appended to the (already-200) stream when generation fails mid-way, so a
# client can distinguish "model finished" from "backend died".
_ERROR_MARKER = "\n\n[ask:error]"
```

Replace the whole `ask_question` endpoint with:
```python
@ask.post("/ask", dependencies=[require("channel.message:send")])
async def ask_question(channel_id: UUID, body: AskRequest, session: SessionDep):
    """Stream a multi-turn RAG answer over the workspace's indexed documents,
    with the channel's own indexed conversation recalled as memory.

    Retrieval runs eagerly (in a worker thread) so Milvus/rewrite failures
    become a real 502 before any bytes stream; generation is iterated via a
    threadpool so LLM work never blocks the event loop.
    """
    async with AsyncSessionLocal() as db:
        workspace_id = await db.scalar(select(Channel.workspace_id).where(Channel.id == channel_id))
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="channel not found")

    history, tail_ids = await _load_unindexed_tail(channel_id, global_rag_config.chat_context_cap)
    asked_at = datetime.now(timezone.utc)
    user_id = cast(UUID, session.sub)

    file_ids = [str(fid) for fid in body.file_ids] if body.file_ids else None
    # TODO: Checking the file ids permissions prior

    chain = RAGChain(
        collection_name=WORKSPACE_COLLECTION,
        workspace_id=str(workspace_id),
        file_ids=file_ids,
        chatroom_id=str(channel_id),
        chat_history=history,
        exclude_message_ids=tail_ids,
    )

    try:
        prepared = await asyncio.to_thread(chain.prepare, body.question)
    except Exception:
        logger.exception("ask retrieval failed", channel_id=str(channel_id))
        raise HTTPException(status_code=502, detail="retrieval failed")

    async def stream():
        parts: list[str] = []
        gen = chain.stream_answer(prepared, include_citations=body.include_citations)
        try:
            async for chunk in iterate_in_threadpool(gen):
                parts.append(chunk)
                yield chunk
        except Exception:
            logger.exception("ask generation failed", channel_id=str(channel_id))
            yield _ERROR_MARKER
            return
        # Persist only the model answer (strip the citation footer).
        answer = "".join(parts).split(_CITATION_MARKER, 1)[0].strip()
        if answer:
            await _persist_exchange(channel_id, user_id, body.question, asked_at, answer)
        if body.debug:
            import json
            payload = chain.trace.as_dict()
            logger.info("ask.debug", model=payload["model"],
                        chat_candidates=len(payload["chat_candidates"]),
                        injected_tail_size=payload["injected_tail_size"])
            yield _DEBUG_MARKER + json.dumps(payload, default=str)

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8")
```

Update imports at the top of the file: add
```python
import asyncio
from datetime import datetime, timezone

from starlette.concurrency import iterate_in_threadpool
```
and REMOVE the now-unused `from chat.service import store_message`.

Also in `_load_unindexed_tail`, exclude SYSTEM notifications (they'd otherwise enter the prompt as fake human turns): add `.where(Message.role != MessageRole.SYSTEM)` after the `indexed_at` filter, and note it in the docstring (`SYSTEM rows (join/leave notices) are skipped — they are not conversation.`).

- [ ] **Step 4: Run the new tests, then the whole suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_ask_endpoint.py -q`
Expected: 5 passed
Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q`
Expected: all pass

- [ ] **Step 5: Sanity-check the fix empirically (optional but recommended)**

If the dev stack is up (uvicorn :8000, Ollama, Milvus): repeat the latency probe from `docs/audits/2026-07-02-deep-audit-findings.md` Part 0 — `/docs` must stay <50ms while an `/ask` streams (was 6.29s before this task).

- [ ] **Step 6: Commit**

```bash
git add src/rag/router.py tests/rag/test_ask_endpoint.py
git commit -m "fix(rag): /ask no longer blocks the event loop; real 502s; atomic post-stream persistence"
```

---

### Task 5: Broadcast the AI answer over Socket.IO (WS option a)

**Files:**
- Modify: `src/rag/router.py` (emit after persistence)
- Test: `tests/rag/test_ask_endpoint.py` (add one test)

**Interfaces:**
- Consumes: `_persist_exchange` return `(question_id, answer_id)` (Task 4); `chat.realtime.sio` (imported READ-ONLY — no teammate file changes).
- Produces: Socket.IO event `ai_message` emitted to room `channel:{channel_id}` with payload keys: `channel_id`, `question_message_id`, `message_id`, `question`, `content`, `role="assistant"`. Clients already in the channel room receive it; the HTTP caller still gets the stream (dual transport, deliberate).

- [ ] **Step 1: Write the failing test** (append to `tests/rag/test_ask_endpoint.py`)

```python
def test_ask_broadcasts_ai_message_to_channel_room(client, test_channel, auth_token, path, monkeypatch):
    from unittest.mock import AsyncMock
    emit = AsyncMock()
    import chat.realtime
    monkeypatch.setattr(chat.realtime.sio, "emit", emit)

    r = _ask(client, path, test_channel, auth_token, include_citations=False)
    assert r.status_code == 200

    emit.assert_awaited_once()
    event, payload = emit.await_args.args[0], emit.await_args.args[1]
    assert event == "ai_message"
    assert emit.await_args.kwargs["room"] == f"channel:{test_channel.id}"
    assert payload["content"] == "hello world"
    assert payload["question"] == "q?"
    assert payload["role"] == "assistant"
    assert payload["channel_id"] == str(test_channel.id)
```

- [ ] **Step 2: Run to verify failure**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_ask_endpoint.py::test_ask_broadcasts_ai_message_to_channel_room -q`
Expected: FAIL (`emit` never awaited)

- [ ] **Step 3: Implement the broadcast**

In `src/rag/router.py` add:
```python
async def _broadcast_ai_message(channel_id: UUID, question_id: UUID, answer_id: UUID,
                                question: str, answer: str) -> None:
    """Fan the finished answer out to everyone in the channel room. The chat
    UI otherwise only shows /ask exchanges to the asker (plain HTTP stream).
    Best-effort: a broadcast failure must never fail the request. NOTE: this
    payload is a custom event, NOT the chat 'message' event — MessageSchema
    requires a non-null sender_id, which assistant rows don't have."""
    try:
        from chat.realtime import sio  # teammate module: import-only, never modified
        await sio.emit(
            "ai_message",
            {
                "channel_id": str(channel_id),
                "question_message_id": str(question_id),
                "message_id": str(answer_id),
                "question": question,
                "content": answer,
                "role": "assistant",
            },
            room=f"channel:{channel_id}",
        )
    except Exception:
        logger.warning("ai_message broadcast failed", channel_id=str(channel_id), exc_info=True)
```

In `stream()` (Task 4's version), replace the persistence block with:
```python
        answer = "".join(parts).split(_CITATION_MARKER, 1)[0].strip()
        if answer:
            q_id, a_id = await _persist_exchange(channel_id, user_id, body.question, asked_at, answer)
            await _broadcast_ai_message(channel_id, q_id, a_id, body.question, answer)
```

- [ ] **Step 4: Run the suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q`
Expected: all pass (the other endpoint tests still pass — `sio.emit` on the real server object is awaited but no client is in the room, which is a no-op; if any test environment lacks Redis, the try/except degrades it to a logged warning).

- [ ] **Step 5: Commit**

```bash
git add src/rag/router.py tests/rag/test_ask_endpoint.py
git commit -m "feat(rag): broadcast finished /ask answers to the channel room as ai_message"
```

---

### Task 6: Indexer concurrency lock, retry label, drain loop

**Files:**
- Modify: `src/processing/chat_indexing.py` (advisory lock)
- Modify: `src/processing/chat_tasks.py` (retry label + drain loop)
- Modify: `src/config/config.py` (add `chat_index_max_batches`)
- Test: `tests/chat/test_chat_indexing.py` (add tests)

**Interfaces:**
- Consumes: existing `index_pending_messages(session_factory=None, *, grace_seconds, batch_size, chunk_size, chunk_overlap, ingest=..., purge=...) -> int`.
- Produces: same signature; returns 0 immediately (logged) when another indexer holds the lock. `index_chat_messages` taskiq task now drains up to `chat_index_max_batches` batches per tick and carries `retry_on_error=True, max_retries=3`.

- [ ] **Step 1: Write the failing tests** (append to `tests/chat/test_chat_indexing.py`, reusing that file's existing session/fixture style — read it first and follow its `session_factory` pattern)

```python
def test_indexer_skips_tick_when_lock_held(db_session):
    """Two concurrent indexer runs must not double-process a batch: the
    second run sees the advisory lock and returns 0 without touching Milvus."""
    from sqlalchemy import text
    from database import SessionLocal
    from processing.chat_indexing import INDEXER_LOCK_KEY, index_pending_messages

    calls = {"ingest": 0}

    def fake_ingest(docs):
        calls["ingest"] += 1

    # Hold the lock from a separate session, as a concurrent run would.
    with SessionLocal() as other:
        held = other.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": INDEXER_LOCK_KEY}
        ).scalar()
        assert held is True
        try:
            n = index_pending_messages(
                grace_seconds=0, batch_size=10, chunk_size=1000, chunk_overlap=0,
                ingest=fake_ingest, purge=lambda _mid: None,
            )
            assert n == 0
            assert calls["ingest"] == 0
        finally:
            other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": INDEXER_LOCK_KEY})
            other.commit()


def test_tick_drains_multiple_batches(monkeypatch):
    """A backlog larger than one batch is drained within a single cron tick."""
    import asyncio
    import processing.chat_tasks as chat_tasks

    batches = [500, 500, 3]  # simulated per-call results

    def fake_index(**kwargs):
        return batches.pop(0)

    monkeypatch.setattr(chat_tasks, "index_pending_messages", fake_index)
    monkeypatch.setattr(chat_tasks.global_rag_config, "chat_index_batch_size", 500)
    monkeypatch.setattr(chat_tasks.global_rag_config, "chat_index_max_batches", 10)

    total = asyncio.run(chat_tasks.index_chat_messages.original_func())
    assert total == 1003
    assert batches == []  # stopped after the short batch
```

Note: taskiq's `@broker.task` exposes the wrapped function as `.original_func`; if the existing tests in this file call the task differently, follow their pattern instead.

- [ ] **Step 2: Run to verify failure**

Run: `IS_TEST=1 uv run python -m pytest tests/chat/test_chat_indexing.py -q`
Expected: new tests FAIL (`ImportError: INDEXER_LOCK_KEY` / total == first batch only)

- [ ] **Step 3: Implement the advisory lock**

In `src/processing/chat_indexing.py`:

Add near the top:
```python
from sqlalchemy import select, text

# Session-level Postgres advisory lock key for the chat indexer. Guards against
# concurrent double-runs (overlapping cron ticks across the 2 default taskiq
# worker processes, or Redis-stream redelivery after the 10-min idle timeout):
# purge->ingest->stamp is only idempotent for SEQUENTIAL runs.
INDEXER_LOCK_KEY = 0x7A105C47  # arbitrary constant, unique within the app
```

In `index_pending_messages`, wrap the body: right after `with session_factory() as db:` add
```python
        got = db.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": INDEXER_LOCK_KEY}
        ).scalar()
        if not got:
            logger.info("chat indexer lock held elsewhere; skipping this run")
            return 0
        try:
            ...existing select / build / purge / ingest / stamp / commit body,
            indented one level...
        finally:
            db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": INDEXER_LOCK_KEY})
            db.commit()
```
(Use the session-level `pg_try_advisory_lock`/`pg_advisory_unlock` pair — NOT the `_xact_` variant — because the existing body performs its own `db.commit()`, which would release a transaction-scoped lock before ingest finishes on some code paths.)

- [ ] **Step 4: Implement retry label + drain loop**

Replace the task in `src/processing/chat_tasks.py`:
```python
@broker.task(schedule=[{"cron": _CRON}], retry_on_error=True, max_retries=3)
async def index_chat_messages() -> int:
    """Embed settled, un-indexed chat messages into Milvus. Drains up to
    chat_index_max_batches batches per tick so a backlog burst clears in one
    tick instead of one batch per 5 minutes. retry_on_error gives transient
    Milvus/embedding failures 3 immediate retries (the RedisStreamBroker
    ignores the delay label, so retries are immediate; the next cron tick
    remains the durable fallback)."""
    total = 0
    for _ in range(max(global_rag_config.chat_index_max_batches, 1)):
        n = await asyncio.to_thread(
            index_pending_messages,
            grace_seconds=global_rag_config.chat_index_grace_seconds,
            batch_size=global_rag_config.chat_index_batch_size,
            chunk_size=global_rag_config.chunk_size,
            chunk_overlap=global_rag_config.chunk_overlap,
        )
        total += n
        if n < global_rag_config.chat_index_batch_size:
            break
    if total:
        logger.info("chat indexer tick complete", indexed=total)
    return total
```

In `src/config/config.py`, next to the other `chat_index_*` fields add:
```python
    # Max batches drained per cron tick (backlog burst recovery); each batch is
    # chat_index_batch_size messages.
    chat_index_max_batches: int = 10
```

- [ ] **Step 5: Run the suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/processing/chat_indexing.py src/processing/chat_tasks.py src/config/config.py tests/chat/test_chat_indexing.py
git commit -m "fix(processing): advisory lock + retries + multi-batch drain for the chat indexer"
```

---

### Task 7: Segment-grouped chat indexing

**Files:**
- Modify: `src/processing/chat_indexing.py` (`build_chat_segments`, rework `build_chat_documents`)
- Modify: `src/rag/vector_store.py` (add `delete_chat_segments_for_messages`)
- Modify: `src/rag/rag_chain.py` (tail-dedupe works on segment docs)
- Modify: `src/config/config.py` (segmentation knobs)
- Test: `tests/chat/test_chat_indexing.py`, `tests/rag/test_chat_recall_dedupe.py`

**Interfaces:**
- Consumes: `message_text` (Task 2), indexer lock (Task 6).
- Produces:
  - `build_chat_segments(messages, *, gap_seconds: int, max_messages: int) -> list[list[Message]]` — groups a mixed-channel batch into per-channel, chronologic, inactivity-gap-bounded segments.
  - `build_chat_documents(messages, chunk_size, chunk_overlap, *, gap_seconds, max_messages) -> list[Document]` — NOTE the two new keyword-only params; metadata per doc is now `{"chatroom_id", "source": "chat", "segment_id", "message_ids": [str, ...], "sent_at_start", "sent_at_end", "chunk_index"}` (no more single `message_id`).
  - `delete_chat_segments_for_messages(message_ids: list[str], collection_name=WORKSPACE_COLLECTION)` in vector_store — the indexer's new purge.
  - RAGChain `_retrieve_chat` drops a recalled doc when ANY of its `message_ids` overlaps `exclude_message_ids` (still supports legacy single-`message_id` docs).

**Rationale (for the reviewer):** SeCom (ICLR 2025) showed topic-coherent multi-turn segments beat per-message retrieval units (GPT4Score 71.57 vs 65.58, same retriever); a lone "yes, let's do that" embeds meaninglessly. Inactivity gap + size cap is the cheapest online-safe boundary proxy (no extra LLM/embedding calls). See `docs/audits/2026-07-02-deep-audit-findings.md` Part 2A.

- [ ] **Step 1: Write the failing tests** (append to `tests/chat/test_chat_indexing.py`)

```python
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4


def _msg(channel, minute, content="hi", role="user"):
    return SimpleNamespace(
        id=uuid4(), channel_id=channel, role=role, content=content,
        sent_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minute),
    )


class TestBuildChatSegments:
    def test_splits_on_inactivity_gap(self):
        from processing.chat_indexing import build_chat_segments
        ch = uuid4()
        msgs = [_msg(ch, 0), _msg(ch, 1), _msg(ch, 45), _msg(ch, 46)]
        segs = build_chat_segments(msgs, gap_seconds=30 * 60, max_messages=12)
        assert [len(s) for s in segs] == [2, 2]

    def test_splits_on_max_messages(self):
        from processing.chat_indexing import build_chat_segments
        ch = uuid4()
        msgs = [_msg(ch, i) for i in range(5)]
        segs = build_chat_segments(msgs, gap_seconds=3600, max_messages=2)
        assert [len(s) for s in segs] == [2, 2, 1]

    def test_never_mixes_channels(self):
        from processing.chat_indexing import build_chat_segments
        a, b = uuid4(), uuid4()
        msgs = [_msg(a, 0), _msg(b, 0), _msg(a, 1), _msg(b, 1)]
        segs = build_chat_segments(msgs, gap_seconds=3600, max_messages=12)
        assert len(segs) == 2
        for seg in segs:
            assert len({m.channel_id for m in seg}) == 1


class TestSegmentDocuments:
    def test_segment_document_metadata(self):
        from processing.chat_indexing import build_chat_documents
        ch = uuid4()
        msgs = [_msg(ch, 0, "first"), _msg(ch, 1, "second")]
        docs = build_chat_documents(msgs, chunk_size=1000, chunk_overlap=0,
                                    gap_seconds=1800, max_messages=12)
        assert len(docs) == 1
        d = docs[0]
        assert "first" in d.page_content and "second" in d.page_content
        assert d.metadata["source"] == "chat"
        assert d.metadata["chatroom_id"] == str(ch)
        assert d.metadata["message_ids"] == [str(m.id) for m in msgs]
        assert d.metadata["segment_id"]
        assert d.metadata["sent_at_start"] <= d.metadata["sent_at_end"]
```

- [ ] **Step 2: Run to verify failure**

Run: `IS_TEST=1 uv run python -m pytest tests/chat/test_chat_indexing.py -q`
Expected: new tests FAIL (`ImportError: build_chat_segments` / TypeError on new kwargs). Some PRE-EXISTING tests asserting one-doc-per-message metadata will also fail after Step 3 — update them in Step 4.

- [ ] **Step 3: Implement segmentation**

In `src/processing/chat_indexing.py` replace `build_chat_documents` with:

```python
import uuid
from collections import defaultdict


def build_chat_segments(messages, *, gap_seconds: int, max_messages: int) -> list[list]:
    """Group settled messages into per-channel conversation segments.

    Boundary = channel change, inactivity gap > gap_seconds, or max_messages.
    Segments are the retrieval unit (SeCom: topic-coherent multi-turn segments
    outperform per-message embeddings); an inactivity gap is the cheapest
    online-safe topic-boundary proxy — no extra LLM/embedding calls.
    """
    by_channel: dict = defaultdict(list)
    for m in messages:
        by_channel[m.channel_id].append(m)

    segments: list[list] = []
    for channel_msgs in by_channel.values():
        channel_msgs.sort(key=lambda m: m.sent_at)
        current: list = []
        for m in channel_msgs:
            gap_exceeded = current and (m.sent_at - current[-1].sent_at).total_seconds() > gap_seconds
            if current and (gap_exceeded or len(current) >= max_messages):
                segments.append(current)
                current = []
            current.append(m)
        if current:
            segments.append(current)
    return segments


def build_chat_documents(messages, chunk_size: int, chunk_overlap: int,
                         *, gap_seconds: int, max_messages: int) -> list[Document]:
    """Build Milvus-ready Documents: one Document per conversation SEGMENT
    (split further only if a segment exceeds chunk_size). Metadata carries the
    full message_ids list so purge and tail-dedupe can match any member."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    docs: list[Document] = []
    for segment in build_chat_segments(messages, gap_seconds=gap_seconds, max_messages=max_messages):
        text = "\n".join(f"{_role_str(m.role)}: {message_text(m)}" for m in segment)
        meta = {
            "chatroom_id": str(segment[0].channel_id),
            "source": "chat",
            "segment_id": str(uuid.uuid4()),
            "message_ids": [str(m.id) for m in segment],
            "sent_at_start": segment[0].sent_at.isoformat() if segment[0].sent_at else "",
            "sent_at_end": segment[-1].sent_at.isoformat() if segment[-1].sent_at else "",
        }
        pieces = splitter.split_text(text) or [text]
        for i, piece in enumerate(pieces):
            docs.append(Document(page_content=piece, metadata={**meta, "chunk_index": i}))
    return docs
```

Update `index_pending_messages`: change its signature's keyword params to also accept `gap_seconds`-style values via config at the call site — concretely, change the `docs = build_chat_documents(messages, chunk_size, chunk_overlap)` call to:
```python
        docs = build_chat_documents(
            messages, chunk_size, chunk_overlap,
            gap_seconds=segment_gap_seconds, max_messages=segment_max_messages,
        )
```
and add `segment_gap_seconds: int = 1800, segment_max_messages: int = 12` keyword-only parameters to `index_pending_messages`. Change the purge step from per-message `purge(str(m.id))` to one call:
```python
        # Idempotency: drop any segment vectors a prior crashed tick may have
        # inserted covering ANY of these messages, before re-inserting.
        purge([str(m.id) for m in messages])
```
and change the default `purge=delete_message_chunks` to `purge=delete_chat_segments_for_messages` (import it from `rag.vector_store`).

In `src/processing/chat_tasks.py`, pass the new config through:
```python
            segment_gap_seconds=global_rag_config.chat_segment_gap_minutes * 60,
            segment_max_messages=global_rag_config.chat_segment_max_messages,
```

In `src/config/config.py` add next to the chat knobs:
```python
    # Conversation segmentation for chat-memory indexing: a segment closes on
    # an inactivity gap or a size cap; segments (not single messages) are the
    # embedded retrieval unit.
    chat_segment_gap_minutes: int = 30
    chat_segment_max_messages: int = 12
```

- [ ] **Step 4: Implement the segment purge in vector_store**

In `src/rag/vector_store.py`, next to `delete_message_chunks` (keep that function — it still purges legacy per-message vectors and is used if a single message is ever deleted), add:

```python
def delete_chat_segments_for_messages(
    message_ids: list[str],
    collection_name: str = WORKSPACE_COLLECTION,
):
    """Delete every chat-memory segment vector that covers ANY of the given
    message_ids. The indexer calls this before re-ingesting a batch so a
    crashed previous tick can't leave duplicate segment vectors."""
    if not message_ids:
        return
    _ensure_milvus_connection()
    if not utility.has_collection(collection_name):
        return

    from pymilvus import MilvusClient
    import json

    client = MilvusClient(
        uri=f"http://{global_rag_config.milvus_host}:{global_rag_config.milvus_port}"
    )
    ids_json = json.dumps([str(i) for i in message_ids])
    client.delete(
        collection_name=collection_name,
        filter=f'source == "chat" && json_contains_any(message_ids, {ids_json})',
    )
```
(This mirrors `delete_message_chunks` exactly: same `MilvusClient(uri=...)` construction from `global_rag_config`, same `filter=` parameter.)

Export the new function wherever `delete_message_chunks` is exported (`src/rag/__init__.py` / `vector_store.__all__`).

- [ ] **Step 5: Segment-aware tail dedupe in RAGChain**

In `src/rag/rag_chain.py`, `_retrieve_chat`, replace the exclusion filter (lines ~159-161) with:

```python
        if self._exclude_message_ids:
            def _overlaps_tail(d):
                ids = d.metadata.get("message_ids")
                if ids is None:  # legacy per-message docs
                    mid = d.metadata.get("message_id")
                    ids = [mid] if mid else []
                return any(i in self._exclude_message_ids for i in ids)
            docs = [d for d in docs if not _overlaps_tail(d)]
```

Extend `tests/rag/test_chat_recall_dedupe.py` with one test following that file's existing style: a fake chat_retriever returning a segment doc whose `metadata["message_ids"]` contains one tail id → the doc must be dropped; a segment doc with disjoint `message_ids` → kept; a legacy doc with `message_id` in the tail → still dropped.

- [ ] **Step 6: Fix the pre-existing per-message tests**

Update any existing tests in `tests/chat/test_chat_indexing.py` that assert the old `message_id` metadata / per-message doc counts / `purge` being called once-per-message: they now assert segment metadata (`message_ids` list) and a single `purge(list)` call. The indexer's settle/idempotency tests keep their logic — only the purge fake signature changes from `purge(mid)` to `purge(ids: list)`.

- [ ] **Step 7: Run the suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add src/processing/chat_indexing.py src/processing/chat_tasks.py src/rag/vector_store.py src/rag/rag_chain.py src/config/config.py tests/
git commit -m "feat(rag): index chat memory as conversation segments, not single messages"
```

---

### Task 8: Decay + redundancy re-rank for chat recall

**Files:**
- Create: `src/rag/retrieval/chat_selection.py`
- Modify: `src/rag/rag_chain.py` (wire into `_retrieve_chat`)
- Modify: `src/config/config.py` (knobs)
- Test: `tests/rag/test_chat_selection.py`

**Interfaces:**
- Consumes: segment docs with `sent_at_end` metadata (Task 7; falls back to `sent_at` for legacy docs).
- Produces: `select_chat_context(candidates: list[Document], *, k: int, now: datetime, half_life_hours: float, overlap_threshold: float) -> list[Document]` — pure function; candidates arrive in relevance order (rank = position); returns ≤ k docs re-ranked by rank-relevance × time-decay, skipping lexically-redundant picks. RAGChain fetches `chat_recall_fetch_k` candidates and selects `chat_recall_k`.

**Rationale:** generative-agents-style `relevance × recency` scoring plus AdaGReS/MMR-style redundancy suppression, approximated lexically (Jaccard) to stay embedding-free at query time. Rank-based relevance avoids coupling to Milvus' distance metric. See audit findings Part 2A.

- [ ] **Step 1: Write the failing tests**

```python
# tests/rag/test_chat_selection.py
"""Pure re-ranking logic: rank-relevance x time-decay, redundancy suppressed."""
from datetime import datetime, timedelta, timezone

from langchain_core.documents import Document

from rag.retrieval.chat_selection import select_chat_context

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


def _doc(text, hours_old):
    return Document(page_content=text, metadata={
        "sent_at_end": (NOW - timedelta(hours=hours_old)).isoformat()})


def test_recent_beats_slightly_more_relevant_but_ancient():
    docs = [
        _doc("deploy key rotation discussion", hours_old=24 * 365),  # rank 0, a year old
        _doc("we rotated the deploy key yesterday", hours_old=2),    # rank 1, fresh
    ]
    out = select_chat_context(docs, k=1, now=NOW, half_life_hours=168, overlap_threshold=0.6)
    assert out[0].page_content == "we rotated the deploy key yesterday"


def test_old_but_only_candidate_survives():
    docs = [_doc("ancient but unique fact", hours_old=24 * 365)]
    out = select_chat_context(docs, k=3, now=NOW, half_life_hours=168, overlap_threshold=0.6)
    assert len(out) == 1


def test_near_duplicates_suppressed():
    docs = [
        _doc("staging database runs on port 5544", hours_old=1),
        _doc("staging database runs on port 5544 !", hours_old=1),   # near-dupe
        _doc("prod key lives in the vault", hours_old=1),
    ]
    out = select_chat_context(docs, k=2, now=NOW, half_life_hours=168, overlap_threshold=0.6)
    texts = [d.page_content for d in out]
    assert len(texts) == 2
    assert "prod key lives in the vault" in texts


def test_k_caps_output_and_missing_timestamp_is_tolerated():
    docs = [Document(page_content=f"unique text {i}", metadata={}) for i in range(5)]
    out = select_chat_context(docs, k=3, now=NOW, half_life_hours=168, overlap_threshold=0.6)
    assert len(out) == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_chat_selection.py -q`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```python
# src/rag/retrieval/chat_selection.py
"""Query-time re-ranking of recalled chat segments.

score = rank_relevance * (floor + (1-floor) * 0.5^(age_h/half_life)), then a
greedy pick that skips candidates lexically redundant (Jaccard) with an
already-picked one. Rank-based relevance (1/(1+rank)) keeps this independent
of Milvus' distance metric; the decay floor keeps an old-but-uniquely-relevant
segment retrievable instead of decaying to zero.
"""
from datetime import datetime

from langchain_core.documents import Document

__all__ = ["select_chat_context"]

_DECAY_FLOOR = 0.25


def _age_hours(doc: Document, now: datetime) -> float:
    stamp = doc.metadata.get("sent_at_end") or doc.metadata.get("sent_at") or ""
    try:
        then = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return 0.0
    return max((now - then).total_seconds() / 3600.0, 0.0)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def select_chat_context(
    candidates: list[Document],
    *,
    k: int,
    now: datetime,
    half_life_hours: float,
    overlap_threshold: float,
) -> list[Document]:
    scored = []
    for rank, doc in enumerate(candidates):
        relevance = 1.0 / (1.0 + rank)
        decay = 0.5 ** (_age_hours(doc, now) / half_life_hours)
        recency = _DECAY_FLOOR + (1.0 - _DECAY_FLOOR) * decay
        scored.append((relevance * recency, rank, doc))
    scored.sort(key=lambda t: (-t[0], t[1]))

    picked: list[Document] = []
    picked_tokens: list[set[str]] = []
    for _score, _rank, doc in scored:
        if len(picked) >= k:
            break
        tokens = set(doc.page_content.lower().split())
        if any(_jaccard(tokens, seen) > overlap_threshold for seen in picked_tokens):
            continue
        picked.append(doc)
        picked_tokens.append(tokens)
    return picked
```

- [ ] **Step 4: Run to verify pass**

Run: `IS_TEST=1 uv run python -m pytest tests/rag/test_chat_selection.py -q`
Expected: 4 passed

- [ ] **Step 5: Wire into RAGChain**

In `src/config/config.py` add:
```python
    # Chat recall re-ranking: fetch a wider candidate pool, then re-rank by
    # rank-relevance x time-decay with lexical redundancy suppression down to
    # chat_recall_k.
    chat_recall_fetch_k: int = 10
    chat_decay_half_life_hours: float = 168.0  # one week
    chat_recall_overlap_threshold: float = 0.6
```

In `src/rag/rag_chain.py`:
- Where the chat retriever is built (line ~101), fetch the wider pool:
```python
                    self.chat_retriever = chat_vs.as_retriever(
                        search_kwargs={"k": config.chat_recall_fetch_k, "expr": chat_expr}
                    )
```
- In `_retrieve_chat`, after the tail-dedupe filter, add the selection step (imports at top of file: `from datetime import datetime, timezone` and `from .retrieval.chat_selection import select_chat_context`):
```python
        docs = select_chat_context(
            docs,
            k=self.config.chat_recall_k,
            now=datetime.now(timezone.utc),
            half_life_hours=self.config.chat_decay_half_life_hours,
            overlap_threshold=self.config.chat_recall_overlap_threshold,
        )
        return docs
```
(Injected `chat_retriever` fakes in tests flow through the same path — candidates without timestamps decay by 0 hours, so pure-relevance order is preserved.)

- [ ] **Step 6: Run the suite**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q`
Expected: all pass (if a dedupe test asserted exact doc lists AND order, rank order is preserved for same-age docs — fix only if it asserted more than k docs surviving).

- [ ] **Step 7: Commit**

```bash
git add src/rag/retrieval/chat_selection.py src/rag/rag_chain.py src/config/config.py tests/rag/test_chat_selection.py
git commit -m "feat(rag): time-decay + redundancy re-ranking for chat recall"
```

---

### Task 9: Docs, hygiene, handoff

**Files:**
- Modify: `.gitignore` (repo root — one-line additions only)
- Modify: `docs/chat-memory-handoff.md`
- Delete (untracked, after gitignoring): `HOW_TO_TEST_ASK.txt` stays LOCAL but must never be committed

**Interfaces:** none (documentation).

- [ ] **Step 1: Gitignore the local-only files**

Append to `.gitignore`:
```
# local /ask test harness (contains session tokens) + throwaway test UI
HOW_TO_TEST_ASK.txt
chat-ui/
```

- [ ] **Step 2: Update the handoff doc**

In `docs/chat-memory-handoff.md`:
- Update the caveats section: rich-msg's `content: str -> JSONB` now funnels through `src/rag/message_text.py` for BOTH read sites (`build_chat_documents`, `_load_unindexed_tail`); the remaining rich-msg touchpoint is `_persist_exchange` in `src/rag/router.py`, which WRITES `content=<str>` directly and must switch to rich-msg's `set_content()` when that branch lands.
- Document the new Socket.IO event for the frontend team: `ai_message` on room `channel:{id}` with payload `{channel_id, question_message_id, message_id, question, content, role}`.
- Document ops invariants: exactly ONE taskiq scheduler instance (taskiq requirement — duplicate schedulers double every tick); the indexer holds Postgres advisory lock `0x7A105C47`; retry = 3 immediate attempts then next tick.
- Document the segment migration: existing per-message chat vectors remain valid for recall but are a different unit; to fully migrate, run `UPDATE messages SET indexed_at = NULL;` (dev DB) after purging chat vectors (`delete` where `source == "chat"`), then let the indexer re-embed as segments.
- Note that `docs/rag-manual/RAG_Owners_Manual.pdf` predates this plan (prepare/stream split, segments, re-ranking, ai_message) and needs regeneration via `docs/rag-manual/gen_diagrams.py` + the `.typ` source — follow-up, not part of this plan.

- [ ] **Step 3: Verify nothing sensitive is staged**

Run: `git status --short`
Expected: `HOW_TO_TEST_ASK.txt` and `chat-ui/` no longer appear (ignored). Run `git diff --cached --stat` before committing — only `.gitignore` and `docs/chat-memory-handoff.md`.

- [ ] **Step 4: Run the full suite one last time**

Run: `IS_TEST=1 uv run python -m pytest tests/rag tests/chat -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add .gitignore docs/chat-memory-handoff.md
git commit -m "docs(chat-memory): handoff updates for segments, ai_message event, indexer ops"
```

---

## Out of scope (deliberately)

- **WS option (c)** (taskiq worker + write-only AsyncRedisManager): the clean end-state if streaming-to-room is ever wanted; option (a) covers the product need with 1/10th the moving parts.
- **Eval coverage for the chat-memory tiers & the hybrid-dead-in-prod parity gap**: requires the ablation run (blocked on an OpenAI key — old Task 8 of the hardening plan).
- **Per-file ACL check for `file_ids`** (router TODO): cross-workspace access is already blocked by the Milvus `workspace_id` conjunct; intra-workspace file ACLs don't exist yet in Talos.
- **The teammate bug** `chat/router.py:39` (unawaited `sio.send`): report to kiro; do NOT fix in their file.
- **Owner's-manual regeneration**: follow-up after this plan lands.
