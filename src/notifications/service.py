import uuid
from typing import Any, Sequence, Iterable

from sqlalchemy import select, func, orm
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from taskiq.decor import AsyncTaskiqDecoratedTask

from utils.datetime import utcnow
from utils.logger import get_logger
from .model import Notification, NotificationsType, NotificationsChannel, NotificationDelivery


def push_notification(
        db: Session,
        user_ids: Iterable[uuid.UUID] | uuid.UUID,
        notif_type: NotificationsType,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        channels: Iterable[NotificationsChannel] | None = None,
) -> list[Notification]:
    """Push a notification to one or more users and enqueue delivery tasks for the specified channels."""

    user_ids = [user_ids] if isinstance(user_ids, uuid.UUID) else list(user_ids)
    # TODO: query user preferences for channels and filter channels accordingly before enqueueing
    notifications = [
        Notification(
            user_id=user_id,
            type=notif_type,
            title=title,
            body=body,
            data=data or {},
        )
        for user_id in user_ids
    ]

    db.add_all(notifications)
    db.flush()

    enqueue_notifications(
        notifications,
        channels or [NotificationsChannel.PUSH],
        db
    )

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


async def enqueue_notifications(
        notifications: Iterable[Notification],
        channels: Iterable[NotificationsChannel],
        db: orm.Session
):
    queued = db.execute(
        insert(NotificationDelivery).values([
            {
                'notification_id': n.id,
                'channel': channel,
            }
            for n in notifications
            for channel in channels
        ]).on_conflict_do_nothing()  # avoid duplicate deliveries if re-enqueued
        .returning(NotificationDelivery.notification_id, NotificationDelivery.channel)
    )
    db.commit()

    # enqueue tasks for each channel
    for notification_id, channel in queued:
        from notifications import tasks
        task: AsyncTaskiqDecoratedTask | None = getattr(tasks, channel.value, None)

        if task:
            await task.kiq(notification_id=notification_id, channels=[channel])
        else:
            get_logger(__name__).warning(f'No task found for channel {channel} in broker task')
