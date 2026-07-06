"""First tests for the /ask HTTP surface. RAGChain is monkeypatched so no
Milvus/LLM is touched; fixtures (client, test_channel, auth_token, path) come
from tests/conftest.py.

Persistence is verified with a direct DB read instead of GET /messages: the
chat listing endpoint currently 500s-into-[] on any assistant row because
MessageSchema.sender_id is non-optional while assistant rows have sender_id
NULL (pre-existing chat-storage bug, reported to the chat owner)."""
import json

import pytest

from chat.model import MessageRole
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


def _messages(channel_id):
    import chat.model, workspace.model, filesystem.model, notifications.model  # mapper registration
    from database import SessionLocal
    from chat.model import Message
    from sqlalchemy import select
    with SessionLocal() as db:
        rows = db.scalars(select(Message).where(Message.channel_id == channel_id)
                          .order_by(Message.sent_at.asc())).all()
        from rag.message_text import doc_text
        return [(m.role, doc_text(m.content), m.sender_id) for m in rows]


def test_ask_streams_and_persists_exchange(client, test_channel, auth_token, path):
    r = _ask(client, path, test_channel, auth_token, include_citations=False)
    assert r.status_code == 200
    assert r.text == "hello world"
    rows = _messages(test_channel.id)
    # question + answer both persisted, question ordered first
    assert len(rows) == 2
    q_role, q_content, q_sender = rows[0]
    a_role, a_content, a_sender = rows[1]
    assert q_role == MessageRole.USER
    assert q_content == "q?"
    assert q_sender is not None
    assert a_role == MessageRole.ASSISTANT
    assert a_content == "hello world"
    assert a_sender is None


def test_ask_prepare_failure_is_502_and_persists_nothing(client, test_channel, auth_token, path, fake_chain):
    fake_chain.fail_prepare = True
    r = _ask(client, path, test_channel, auth_token)
    assert r.status_code == 502
    assert _messages(test_channel.id) == []


def test_ask_midstream_failure_marks_stream_and_persists_nothing(client, test_channel, auth_token, path, fake_chain):
    fake_chain.fail_stream = True
    r = _ask(client, path, test_channel, auth_token, include_citations=False)
    assert r.status_code == 200          # headers were already sent
    assert r.text.startswith("hello ")
    assert "[ask:error]" in r.text       # client can detect the failure
    assert _messages(test_channel.id) == []


def test_ask_debug_appends_trace_payload(client, test_channel, auth_token, path):
    r = _ask(client, path, test_channel, auth_token, include_citations=False, debug=True)
    body, _, dbg = r.text.partition("__ASK_DEBUG__")
    assert "hello world" in body
    payload = json.loads(dbg)
    assert "model" in payload and "chat_candidates" in payload


def test_ask_citation_footer_stripped_from_persisted_answer(client, test_channel, auth_token, path):
    r = _ask(client, path, test_channel, auth_token, include_citations=True)
    assert "Sources:" in r.text
    assistant = [(c, s) for role, c, s in _messages(test_channel.id) if role == MessageRole.ASSISTANT]
    assert assistant == [("hello world", None)]


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
    assert payload["request_id"]


def test_ask_uses_workspace_ai_overrides(client, test_channel, auth_token, path, fake_chain):
    r = client.patch(f"/api/workspaces/{test_channel.workspace_id}/ai/config",
                     json={"use_reranking": False, "retrieval_top_k": 2},
                     headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200

    _ask(client, path, test_channel, auth_token, include_citations=False)
    cfg = fake_chain.last.kwargs.get("config")
    assert cfg is not None
    assert cfg.use_reranking is False
    assert cfg.retrieval_top_k == 2
    prov = fake_chain.last.kwargs.get("config_provenance")
    assert prov["use_reranking"] == "workspace"
    # cleanup
    client.patch(f"/api/workspaces/{test_channel.workspace_id}/ai/config",
                 json={"use_reranking": None, "retrieval_top_k": None},
                 headers={"Authorization": f"Bearer {auth_token}"})


def test_ask_uses_channel_ai_overrides(client, test_channel, auth_token, path, fake_chain):
    r = client.patch(f"/api/workspaces/{test_channel.workspace_id}/ai/config",
                     json={"retrieval_top_k": 9},
                     headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200

    r = client.patch(f"/api/channels/{test_channel.id}/ai/config",
                     json={"retrieval_top_k": 2},
                     headers={"Authorization": f"Bearer {auth_token}"})
    assert r.status_code == 200

    try:
        _ask(client, path, test_channel, auth_token, include_citations=False)
        cfg = fake_chain.last.kwargs.get("config")
        assert cfg is not None
        assert cfg.retrieval_top_k == 2
        prov = fake_chain.last.kwargs.get("config_provenance")
        assert prov["retrieval_top_k"] == "channel"
    finally:
        # cleanup
        client.patch(f"/api/channels/{test_channel.id}/ai/config",
                     json={"retrieval_top_k": None},
                     headers={"Authorization": f"Bearer {auth_token}"})
        client.patch(f"/api/workspaces/{test_channel.workspace_id}/ai/config",
                     json={"retrieval_top_k": None},
                     headers={"Authorization": f"Bearer {auth_token}"})


def _seed_unindexed(channel_id, contents):
    """Seed un-indexed USER messages (oldest -> newest) directly; returns ids."""
    import time
    from datetime import datetime, timedelta, timezone
    import chat.model, workspace.model, filesystem.model, notifications.model  # noqa: F401
    from database import SessionLocal
    from chat.model import Message, MessageRole as MR
    base = datetime.now(timezone.utc)
    ids = []
    with SessionLocal() as db:
        for i, content in enumerate(contents):
            m = Message(channel_id=channel_id, sender_id=None, role=MR.USER,
                        content=content, sent_at=base + timedelta(seconds=i))
            # sender_id NULL is fine for the tail loader; avoids user fixtures
            db.add(m)
            db.flush()  # the id default fires at flush, not at construction
            ids.append(m.id)
        db.commit()
    return ids


def _delete_messages(ids):
    from database import SessionLocal
    from chat.model import Message
    with SessionLocal() as db:
        for mid in ids:
            row = db.get(Message, mid)
            if row is not None:
                db.delete(row)
        db.commit()


def test_tail_respects_char_budget(client, test_channel, auth_token, path, fake_chain, monkeypatch):
    """A burst of huge un-indexed messages must NOT all be injected: the tail
    keeps newest-first within chat_context_char_budget (never empty)."""
    from config import global_rag_config
    monkeypatch.setattr(global_rag_config, "chat_context_char_budget", 16000)
    ids = _seed_unindexed(test_channel.id, ["A" * 10000, "B" * 10000, "C" * 10000])
    try:
        _ask(client, path, test_channel, auth_token, include_citations=False)
        history = fake_chain.last.kwargs["chat_history"]
        # Only the newest (C) fits: C=10k, +B would be 20k > 16k budget.
        assert len(history) == 1
        assert history[0].content == "C" * 10000
        # exclusion set must match what was actually injected
        assert fake_chain.last.kwargs["exclude_message_ids"] == {str(ids[2])}
    finally:
        _delete_messages(ids)


def test_tail_never_empty_even_if_newest_exceeds_budget(client, test_channel, auth_token, path, fake_chain, monkeypatch):
    """A single message larger than the whole budget is still injected whole —
    the budget bounds accumulation, it never silently truncates content."""
    from config import global_rag_config
    monkeypatch.setattr(global_rag_config, "chat_context_char_budget", 16000)
    ids = _seed_unindexed(test_channel.id, ["X" * 50000])
    try:
        _ask(client, path, test_channel, auth_token, include_citations=False)
        history = fake_chain.last.kwargs["chat_history"]
        assert len(history) == 1
        assert history[0].content == "X" * 50000
    finally:
        _delete_messages(ids)
