"""Tests for the chat-memory indexer (processing/chat_indexing.py)."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from chat.model import Message, MessageRole
from database import SessionLocal
from processing.chat_indexing import build_chat_documents, index_pending_messages
from utils.datetime import utcnow


def _msg(content, role="user", channel_id="ch-1", mid="m1"):
    return SimpleNamespace(
        id=mid, channel_id=channel_id, content=content,
        role=role, sent_at=utcnow(),
    )


class TestBuildChatDocuments:
    def test_one_document_per_short_message(self):
        docs = build_chat_documents([_msg("hello there")], chunk_size=1000, chunk_overlap=0)
        assert len(docs) == 1
        d = docs[0]
        assert d.page_content == "user: hello there"
        assert d.metadata["source"] == "chat"
        assert d.metadata["chatroom_id"] == "ch-1"
        assert d.metadata["message_id"] == "m1"
        assert d.metadata["chunk_index"] == 0

    def test_long_message_is_split(self):
        docs = build_chat_documents([_msg("word " * 600)], chunk_size=200, chunk_overlap=0)
        assert len(docs) > 1
        assert all(d.metadata["message_id"] == "m1" for d in docs)
        assert [d.metadata["chunk_index"] for d in docs] == list(range(len(docs)))

    def test_role_prefix_uses_role_column(self):
        docs = build_chat_documents(
            [_msg("the answer", role=MessageRole.ASSISTANT)], chunk_size=1000, chunk_overlap=0
        )
        assert docs[0].page_content == "assistant: the answer"


class TestIndexPendingMessages:
    def test_indexes_settled_skips_fresh_and_is_idempotent(self, db_session, test_channel, test_user):
        captured = []
        ch_id, user_id = test_channel.id, test_user.id

        # One settled (old) message and one fresh message, committed so the
        # indexer's own session sees them.
        with SessionLocal() as s:
            old = Message(channel_id=ch_id, sender_id=user_id, content="old message",
                          role=MessageRole.USER, sent_at=utcnow() - timedelta(seconds=600))
            fresh = Message(channel_id=ch_id, sender_id=user_id, content="fresh message",
                            role=MessageRole.USER, sent_at=utcnow())
            s.add_all([old, fresh])
            s.commit()
            old_id, fresh_id = old.id, fresh.id

        n = index_pending_messages(
            grace_seconds=300, batch_size=100, chunk_size=1000, chunk_overlap=0,
            ingest=lambda docs: captured.extend(docs),
            purge=lambda _mid: None,
        )

        assert n == 1
        assert [d.metadata["message_id"] for d in captured] == [str(old_id)]

        with SessionLocal() as s:
            assert s.get(Message, old_id).indexed_at is not None
            assert s.get(Message, fresh_id).indexed_at is None

        # Idempotent: the fresh message is still too young, nothing new to index.
        assert index_pending_messages(
            grace_seconds=300, batch_size=100, chunk_size=1000, chunk_overlap=0,
            ingest=lambda docs: None, purge=lambda _mid: None,
        ) == 0
