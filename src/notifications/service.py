import itertools
import uuid
from typing import Any, Sequence, Iterable

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from utils.datetime import utcnow
from . import tasks
from .model import Notification, NotificationsChannel, NotificationDelivery


async def push_notification(
        db: Session,
        user_ids: Iterable[uuid.UUID] | uuid.UUID,
        title: str, body: str,
        data: dict[str, Any] | None = None,
        tags: Iterable[str] | None = None,
) -> list[Notification]:
    """Push a notification to one or more users and enqueue delivery tasks for the specified channels."""
    user_ids = [user_ids] if isinstance(user_ids, uuid.UUID) else list(user_ids)

    tags_list = list(tags) if tags is not None else []

    # TODO: query user preferences for channels and filter channels accordingly before enqueueing
    notifications = [
        Notification(
            user_id=user_id,
            title=title,
            body=body,
            data=data or {},
            tags=tags_list,
        )
        for user_id in user_ids
    ]

    db.add_all(notifications)
    db.commit()

    # enqueue tasks for each channel (default to all channels; user prefs TODO)
    channels = list(NotificationsChannel)

    for n, channel in itertools.product(notifications, channels):
        match channel:
            # TODO: is online check
            case NotificationsChannel.EMAIL:
                # If tasks.email exposes kiq wrapper, prefer it; otherwise call coroutine directly
                if hasattr(tasks.email, "kiq"):
                    await tasks.email.kiq(notification_id=n.id)
                else:
                    await tasks.email(notification_id=n.id)
                n.deliveries.append(NotificationDelivery(channel=channel))
            case NotificationsChannel.PUSH:
                await tasks.web_push(notification_id=n.id)
                n.deliveries.append(NotificationDelivery(channel=channel))
            case NotificationsChannel.IN_APP:
                # in-app delivery requires no external worker
                n.deliveries.append(NotificationDelivery(channel=channel))

    db.commit()

    return notifications


def mark_as_read(
        db: Session,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
) -> bool:
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id
    ).first()

    if not notification:
        return False

    notification.read_at = utcnow()
    db.commit()

    return True


def get_user_notifications(
        db: Session,
        user_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
) -> Sequence[Notification]:
    stmt = select(Notification).where(
        Notification.user_id == user_id
    )

    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))

    return db.scalars(
        stmt
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()


def get_unread_count(db: Session, user_id: uuid.UUID) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None)
        )
    )
    return count or 0
