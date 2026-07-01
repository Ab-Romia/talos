"""Scheduled taskiq tasks for chat-memory indexing.

The cron fires from the taskiq scheduler (see ``src/scheduler.py``), which sends
this task to the broker; the taskiq worker executes it. The blocking indexer
(DB + Milvus + embeddings) runs in a thread so the async worker loop is free.
"""

import asyncio

from broker import broker
from config import global_rag_config
from processing.chat_indexing import index_pending_messages
from utils.logger import get_logger

logger = get_logger(__name__)

# Fire every `chat_index_interval_minutes` (evaluated at import).
_CRON = f"*/{max(global_rag_config.chat_index_interval_minutes, 1)} * * * *"


@broker.task(schedule=[{"cron": _CRON}])
async def index_chat_messages() -> int:
    """Embed settled, un-indexed chat messages into Milvus. Returns the count."""
    n = await asyncio.to_thread(
        index_pending_messages,
        grace_seconds=global_rag_config.chat_index_grace_seconds,
        batch_size=global_rag_config.chat_index_batch_size,
        chunk_size=global_rag_config.chunk_size,
        chunk_overlap=global_rag_config.chunk_overlap,
    )
    if n:
        logger.info("chat indexer tick complete", indexed=n)
    return n
