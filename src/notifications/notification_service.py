import uuid
from typing import Any, Sequence, Iterable

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .model import Notification, NotificationsType, NotificationsChannel
from .notification_worker import publish_message


# TODO: notifications should be per session, not per user

def push_notification(
        db: Session,
        user_id: uuid.UUID,
        notif_type: NotificationsType,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        channels: list[NotificationsChannel] | None = None,
) -> Notification:
    return push_bulk_notification(
        db=db,
        user_ids=[user_id],
        type_=notif_type,
        title=title,
        body=body,
        data=data,
        channels=channels,
    )[0]


def push_bulk_notification(
        db: Session,
        user_ids: Iterable[uuid.UUID],
        type_: NotificationsType,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        channels: Iterable[NotificationsChannel] | None = None,
) -> list[Notification]:
    notifications = [
        Notification(
            user_id=user_id,
            type=type_,
            title=title,
            body=body,
            data=data or {},
        )
        for user_id in user_ids
    ]

    db.add_all(notifications)
    db.commit()

    # refresh to get IDs
    for n in notifications:
        db.refresh(n)

    # enqueue all
    for n in notifications:
        channels1 = channels or [NotificationsChannel.in_app]
        payload = {
            "notification_id": n.id,
            "user_id": n.user_id,
            "channels": [c.value for c in channels1],
        }
        publish_message(payload)

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

    notification.is_read = True
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
        stmt = stmt.where(Notification.is_read.is_(False))

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
            Notification.is_read.is_(False)
        )
    )
    return count or 0
