import uuid
from typing import List, Optional, Dict, Any, Type

from sqlalchemy.orm import Session

from modules.model.notifications import (
    Notification,
    NotificationsType,
)
from modules.model.notifications import NotificationsChannel
from modules.queue.rabbitmq import publish_message


class NotificationService:

    @staticmethod
    def create_notification(
        db: Session,
        user_id: uuid.UUID,
        type: NotificationsType,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        channels: Optional[List[NotificationsChannel]] = None,
    ) -> Notification:

        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            data=data or {},
        )

        db.add(notification)
        db.commit()
        db.refresh(notification)

        NotificationService.enqueue_notification(
            notification_id=notification.id,
            user_id=user_id,
            channels=channels or [NotificationsChannel.in_app],
        )

        return notification

    @staticmethod
    def create_bulk_notifications(
        db: Session,
        user_ids: List[uuid.UUID],
        type: NotificationsType,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        channels: Optional[List[NotificationsChannel]] = None,
    ) -> List[Notification]:

        notifications = [
            Notification(
                user_id=user_id,
                type=type,
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
            NotificationService.enqueue_notification(
                notification_id=n.id,
                user_id=n.user_id,
                channels=channels or [NotificationsChannel.in_app],
            )

        return notifications

    @staticmethod
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

    @staticmethod
    def get_user_notifications(
        db: Session,
        user_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[Type[Notification]]:

        query = db.query(Notification).filter(
            Notification.user_id == user_id
        )

        if unread_only:
            query = query.filter(Notification.is_read == False)

        return (
            query.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all())

    @staticmethod
    def get_unread_count(
        db: Session,
        user_id: uuid.UUID,
    ) -> int:

        return db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.is_read == False
        ).count()

    @staticmethod
    def enqueue_notification(
            notification_id,
            user_id,
            channels,
    ):
        payload = {
            "notification_id": str(notification_id),
            "user_id": str(user_id),
            "channels": [c.value for c in channels],
        }

        publish_message(payload)