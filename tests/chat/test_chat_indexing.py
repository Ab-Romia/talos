"""Tests for the chat-memory indexer (processing/chat_indexing.py)."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from chat.model import Message, MessageRole
from database import SessionLocal
from processing.chat_indexing import build_chat_documents, index_pending_messages
from utils.datetime import utcnow


def _legacy_msg(content, role="user", channel_id="ch-1", mid="m1"):
    return SimpleNamespace(
        id=mid, channel_id=channel_id, content=content,
        role=role, sent_at=utcnow(),
    )


class TestBuildChatDocuments:
    def test_one_document_per_short_message(self):
        docs = build_chat_documents([_legacy_msg("hello there")], chunk_size=1000, chunk_overlap=0,
                                    gap_seconds=1800, max_messages=12)
        assert len(docs) == 1
        d = docs[0]
        assert d.page_content == "user: hello there"
        assert d.metadata["source"] == "chat"
        assert d.metadata["chatroom_id"] == "ch-1"
        assert d.metadata["message_ids"] == ["m1"]
        assert d.metadata["chunk_index"] == 0

    def test_long_message_is_split(self):
        docs = build_chat_documents([_legacy_msg("word " * 600)], chunk_size=200, chunk_overlap=0,
                                    gap_seconds=1800, max_messages=12)
        assert len(docs) > 1
        assert all(d.metadata["message_ids"] == ["m1"] for d in docs)
        assert [d.metadata["chunk_index"] for d in docs] == list(range(len(docs)))

    def test_role_prefix_uses_role_column(self):
        docs = build_chat_documents(
            [_legacy_msg("the answer", role=MessageRole.ASSISTANT)], chunk_size=1000, chunk_overlap=0,
            gap_seconds=1800, max_messages=12,
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

        purge_calls = []
        n = index_pending_messages(
            grace_seconds=300, batch_size=100, chunk_size=1000, chunk_overlap=0,
            ingest=lambda docs: captured.extend(docs),
            purge=lambda ids: purge_calls.append(ids),
        )

        assert n == 1
        assert [d.metadata["message_ids"] for d in captured] == [[str(old_id)]]
        assert purge_calls == [[str(old_id)]]

        with SessionLocal() as s:
            assert s.get(Message, old_id).indexed_at is not None
            assert s.get(Message, fresh_id).indexed_at is None

        # Idempotent: the fresh message is still too young, nothing new to index.
        assert index_pending_messages(
            grace_seconds=300, batch_size=100, chunk_size=1000, chunk_overlap=0,
            ingest=lambda docs: None, purge=lambda ids: None,
        ) == 0


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


def test_indexer_releases_lock_after_successful_run(db_session, test_channel, test_user):
    """After a run completes (messages indexed and committed), the lock must be
    immediately acquirable by another session — guards the connection-affinity
    leak (unlock must hit the same connection the lock was taken on)."""
    from sqlalchemy import text
    from processing.chat_indexing import INDEXER_LOCK_KEY

    ch_id, user_id = test_channel.id, test_user.id
    with SessionLocal() as s:
        s.add(Message(channel_id=ch_id, sender_id=user_id, content="settled message",
                      role=MessageRole.USER, sent_at=utcnow() - timedelta(seconds=600)))
        s.commit()

    n = index_pending_messages(
        grace_seconds=300, batch_size=100, chunk_size=1000, chunk_overlap=0,
        ingest=lambda docs: None, purge=lambda _mid: None,
    )
    assert n == 1  # a real successful run, with the body's own db.commit()

    # Core invariant: the lock is free again from a fresh session/connection.
    with SessionLocal() as fresh:
        held = fresh.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": INDEXER_LOCK_KEY}
        ).scalar()
        try:
            assert held is True
        finally:
            fresh.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": INDEXER_LOCK_KEY})
            fresh.commit()


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
