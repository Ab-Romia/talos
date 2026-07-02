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
        return [(m.role, m.content, m.sender_id) for m in rows]


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
