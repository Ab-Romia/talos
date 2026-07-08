"""Periodic chat-memory indexer.

Embeds settled, un-indexed chat messages into the shared Milvus collection
(tagged ``source="chat"``, scoped by ``chatroom_id``) so older conversation
becomes retrievable beyond the small un-indexed tail injected directly as
context. Runs from a taskiq cron task (see ``processing.chat_tasks``).

Built against main's schema: ``Message`` has a first-class ``role`` enum column
and ``sent_at`` (no ``message_extra``/``created_at``/``deleted_at``). Chat
vectors are scoped by ``chatroom_id`` (= ``channel_id``, globally unique), so no
``workspace_id`` join is needed.
"""

import uuid
from collections import defaultdict
from datetime import timedelta

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select, text

from rag.ingestion import ingest_chat_messages
from rag.message_text import message_text
from rag.vector_store import delete_chat_segments_for_messages
from utils.datetime import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)

# Session-level Postgres advisory lock key for the chat indexer. Guards against
# concurrent double-runs (overlapping cron ticks across the 2 default taskiq
# worker processes, or Redis-stream redelivery after the 10-min idle timeout):
# purge->ingest->stamp is only idempotent for SEQUENTIAL runs.
# Arbitrary constant, unique within the app; comfortably fits in pg's signed
# 64-bit (bigint) advisory-lock key space.
INDEXER_LOCK_KEY = 0x7A105C47


def _role_str(role) -> str:
    return role.value if hasattr(role, "value") else str(role)


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


def index_pending_messages(
    session_factory=None,
    *,
    grace_seconds: int,
    batch_size: int,
    chunk_size: int,
    chunk_overlap: int,
    ingest=ingest_chat_messages,
    purge=delete_chat_segments_for_messages,
    segment_gap_seconds: int = 1800,
    segment_max_messages: int = 12,
) -> int:
    """Index one batch of settled, un-indexed messages.

    Order is purge -> ingest -> stamp -> commit. Ingest-then-stamp is lose-safe:
    a failure before the stamp leaves the rows un-indexed (retried next tick),
    and the pre-ingest purge stops that retry from duplicating vectors. Returns
    the count indexed.
    """
    from chat.model import Message, MessageRole
    # Register related mappers before querying Message. The taskiq worker is a
    # minimal process (not the full app), so Message.channel -> Channel and
    # Message.files -> File won't resolve unless their modules are imported.
    import workspace.model  # noqa: F401  (Channel, Workspace)
    import filesystem.model  # noqa: F401  (File)

    if session_factory is None:
        from database import SessionLocal
        session_factory = SessionLocal

    cutoff = utcnow() - timedelta(seconds=grace_seconds)

    # Session-level advisory lock on a DEDICATED connection, held for the whole
    # run. Pg session locks bind to the CONNECTION, and the ORM session below
    # commits freely — a commit can return the Session's pooled connection, so
    # the lock must not live there (unlocking on a different pooled connection
    # would silently no-op and leak the lock forever). Crash-safe: if the
    # process dies, pg releases session locks when the connection drops.
    from database import engine

    lock_conn = engine.connect()
    got = False
    try:
        got = lock_conn.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": INDEXER_LOCK_KEY}
        ).scalar()
        if not got:
            logger.info("chat indexer lock held elsewhere; skipping this run")
            return 0
        with session_factory() as db:
            messages = db.scalars(
                select(Message)
                .where(Message.indexed_at.is_(None))
                # soft-deleted messages must not enter chat memory
                .where(Message.is_deleted.is_(False))
                .where(Message.sent_at < cutoff)
                .order_by(Message.sent_at.asc())
                .limit(batch_size)
            ).all()
            if not messages:
                return 0

            # Embed only human conversation. Assistant answers must not enter
            # chat memory: a re-asked question embeds near-identically to its
            # own past Q&A segment, so old AI answers (including refusals)
            # would win recall and crowd out the real content — a feedback
            # loop (store_assistant_message documents the same intent).
            # Assistant rows are still stamped below so the un-indexed tail
            # stays bounded.
            docs = build_chat_documents(
                [m for m in messages if m.role != MessageRole.ASSISTANT],
                chunk_size, chunk_overlap,
                gap_seconds=segment_gap_seconds, max_messages=segment_max_messages,
            )
            # Idempotency: drop any segment vectors a prior crashed tick may have
            # inserted covering ANY of these messages, before re-inserting.
            purge([str(m.id) for m in messages])
            ingest(docs)  # raises on failure -> no stamping, retried next tick

            stamped = utcnow()
            for m in messages:
                m.indexed_at = stamped
            db.commit()
            logger.info("indexed chat messages", count=len(messages))
            return len(messages)
    finally:
        # Only unlock if we actually acquired the lock, else pg logs a
        # "you don't own a lock..." WARNING on every skipped tick. Nest in an
        # inner try/finally so close() still runs even if unlock raises.
        try:
            if got:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": INDEXER_LOCK_KEY})
        finally:
            lock_conn.close()
