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

from datetime import timedelta

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select, text

from rag.ingestion import ingest_chat_messages
from rag.message_text import message_text
from rag.vector_store import delete_message_chunks
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


def build_chat_documents(messages, chunk_size: int, chunk_overlap: int) -> list[Document]:
    """Build Milvus-ready Documents from Message-like objects.

    One Document per short message; messages longer than ``chunk_size`` are
    split, with a contiguous ``chunk_index`` per message. Metadata:
    ``chatroom_id`` (= channel_id), ``message_id``, ``source="chat"``, ``sent_at``.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    docs: list[Document] = []
    for m in messages:
        text = f"{_role_str(m.role)}: {message_text(m)}"
        meta = {
            "chatroom_id": str(m.channel_id),
            "message_id": str(m.id),
            "source": "chat",
            "sent_at": m.sent_at.isoformat() if m.sent_at else "",
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
    purge=delete_message_chunks,
) -> int:
    """Index one batch of settled, un-indexed messages.

    Order is purge -> ingest -> stamp -> commit. Ingest-then-stamp is lose-safe:
    a failure before the stamp leaves the rows un-indexed (retried next tick),
    and the pre-ingest purge stops that retry from duplicating vectors. Returns
    the count indexed.
    """
    from chat.model import Message
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
                .where(Message.sent_at < cutoff)
                .order_by(Message.sent_at.asc())
                .limit(batch_size)
            ).all()
            if not messages:
                return 0

            docs = build_chat_documents(messages, chunk_size, chunk_overlap)
            # Idempotency: drop any vectors a prior crashed tick may have inserted
            # for these messages before re-inserting. No-op on the normal first pass.
            for m in messages:
                purge(str(m.id))
            ingest(docs)  # raises on failure -> no stamping, retried next tick

            stamped = utcnow()
            for m in messages:
                m.indexed_at = stamped
            db.commit()
            logger.info("indexed chat messages", count=len(messages))
            return len(messages)
    finally:
        # On the not-acquired path this unlock is a harmless no-op (returns false).
        lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": INDEXER_LOCK_KEY})
        lock_conn.close()
