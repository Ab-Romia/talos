"""Chat message search service."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import String, select, and_, func
from sqlalchemy.orm import selectinload

from database import AsyncSessionLocal
from utils.exceptions import handle_exceptions
from .model import MessageSchema, Message


@handle_exceptions("Failed to search messages", default_return=([], 0))
async def search_messages(
    channel_id: UUID,
    text: Optional[str] = None,
    author_id: Optional[UUID] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[MessageSchema], int]:
    """
    Search messages within a channel with filtering and pagination.

    Args:
        channel_id: Filter by channel
        text: Search in message content (case-insensitive)
        author_id: Filter by sender_id
        start_date: Filter by sent_at >= start_date
        end_date: Filter by sent_at <= end_date
        limit: Max results per page
        offset: Pagination offset

    Returns:
        Tuple of (messages, total_count)
    """
    async with AsyncSessionLocal() as db:
        # Build base query
        query = select(Message).where(Message.channel_id == channel_id)

        # Apply optional filters
        filters = []

        if text:
            # content is a ProseMirror JSONB doc (rich-msg) — cast to text for
            # a case-insensitive substring match over the serialized doc.
            filters.append(Message.content.cast(String).ilike(f"%{text}%"))

        if author_id:
            filters.append(Message.sender_id == author_id)

        if start_date:
            filters.append(Message.sent_at >= start_date)

        if end_date:
            filters.append(Message.sent_at <= end_date)

        if filters:
            query = query.where(and_(*filters))

        # Get total count before pagination
        count_query = select(func.count()).select_from(Message).where(
            and_(Message.channel_id == channel_id, *filters) if filters else Message.channel_id == channel_id
        )
        total = await db.scalar(count_query) or 0

        # Apply ordering and pagination. Eager-load files: MessageSchema reads the
        # `attachments` property, which walks the files relationship — a lazy load
        # there would fail under the async session (MissingGreenlet).
        query = (
            query.options(selectinload(Message.files))
            .order_by(Message.sent_at.desc())
            .limit(limit)
            .offset(offset)
        )

        rows = await db.scalars(query)
        messages = [MessageSchema.model_validate(row) for row in rows]

        return messages, total

