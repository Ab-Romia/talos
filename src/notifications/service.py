import uuid
from typing import Any, Sequence, Iterable

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from utils.datetime import utcnow
from . import tasks
from .model import Notification, NotificationsChannel, NotificationDelivery, PushSubscription, NotificationSchema, \
    PushSubscriptionSchema, NotificationTag


async def push_notification(
        db: Session,
        user_ids: Iterable[uuid.UUID] | uuid.UUID,
        title: str, body: str,
        data: dict[str, Any] | None = None,
        tags: Iterable[NotificationTag] | None = None,
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

    # Enqueue delivery tasks for each notification
    for n in notifications:
        # TODO: is online check
        is_online = False

        if not is_online:
            subscriptions = db.scalars(
                select(PushSubscription)
                .where(PushSubscription.user_id == n.user_id)
                .where(PushSubscription.expiration_time.is_(None)
                       | (PushSubscription.expiration_time > utcnow()))
                .where(PushSubscription.deleted_at.is_(None))
            ).all()

            # Enqueue web_push for each subscription
            for sub in subscriptions:
                delivery = NotificationDelivery(
                    notification_id=n.id,
                    channel=NotificationsChannel.PUSH,
                    subscription_id=sub.id,
                )
                db.add(delivery)

                await tasks.webpush.kiq(
                    notification=NotificationSchema.model_validate(n),
                    subscription=PushSubscriptionSchema.model_validate(sub)
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


def get_user_notifications(db: Session, user_id: uuid.UUID, limit: int = 20,
                           offset: int = 0, unread_only: bool = False,
                           after_notification_id: uuid.UUID = None) -> Sequence[Notification]:
    stmt = select(Notification).where(
        Notification.user_id == user_id
    )

    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))

    if after_notification_id:
        # TODO: using uuid7 with time-based ordering would eliminate the need for this extra query
        subquery = select(Notification.created_at).where(
            Notification.id == after_notification_id,
            Notification.user_id == user_id
        ).scalar_subquery()
        stmt = stmt.where(Notification.created_at > subquery)

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
