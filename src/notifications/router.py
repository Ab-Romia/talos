import uuid
from datetime import datetime
from typing import Any, Annotated

from fastapi import APIRouter, Query, HTTPException, Body
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from backend.auth.utils.helpers import UserDep
from config import cfg
from model import DatabaseDep
from utils.datetime import utcnow
from . import PushSubscription
from .model import NotificationsType, Notification
from .service import (
    get_user_notifications,
    mark_as_read,
    get_unread_count as get_unread_count_service,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: NotificationsType
    title: str
    body: str
    data: dict[str, Any] | None
    is_read: bool
    created_at: datetime

    @staticmethod
    def from_notification(notification: Notification) -> "NotificationResponse":
        return NotificationResponse(
            id=notification.id,
            type=notification.type,
            title=notification.title,
            body=notification.body,
            data=notification.data,
            is_read=notification.read_at is not None,
            created_at=notification.created_at,
        )

    model_config = ConfigDict(from_attributes=True)


@router.get("/", response_model=list[NotificationResponse])
def get_notifications(
        current_user: UserDep,
        db: DatabaseDep,
        limit: int = Query(20, le=100),
        offset: int = 0,
        unread_only: bool = False,
):
    notifications = get_user_notifications(
        db=db,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
    )

    return [NotificationResponse.from_notification(n) for n in notifications]


@router.post("/read")
def mark_as_read_(notification_id: uuid.UUID, current_user: UserDep, db: DatabaseDep):
    success = mark_as_read(
        db=db,
        user_id=current_user.id,
        notification_id=notification_id,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")


@router.get("/unread-count")
def get_unread_count(db: DatabaseDep, current_user: UserDep):
    count = get_unread_count_service(
        db=db,
        user_id=current_user.id,
    )

    return {"unread_count": count}


@router.post("/read-all")
def mark_all_as_read(db: DatabaseDep, current_user: UserDep):
    notifications = db.scalars(
        select(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.read_at.is_(None)
        )
    ).all()

    for n in notifications:
        n.read_at = utcnow()

    db.commit()

    return {"status": "ok"}


class PushSubscriptionReq(BaseModel):
    endpoint: str
    keys: dict[str, str]
    encodings: list[str] | None = None
    expiration_time: datetime | None = None


@router.get("/vapid-public-key")
def get_vapid_public_key():
    return {"vapid_public_key": cfg().push.vapid_public_key}


@router.get("/subscription")
def get_push_subscription(
        user: UserDep,
        db: DatabaseDep
):
    subscription = db.scalars(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    ).all()

    return [{
        "endpoint": s.endpoint,
        "keys": s.keys,
        "expiration_time": s.expiration_time,
    } for s in subscription]


@router.post("/subscription")
def subscribe_to_push(
        push_subscription: Annotated[PushSubscriptionReq, Body()],
        user: UserDep,
        db: DatabaseDep
):
    # TODO: clean up expired subscriptions periodically
    subscribe = PushSubscription(
        user_id=user.id,
        endpoint=push_subscription.endpoint,
        keys=push_subscription.keys,
        expiration_time=push_subscription.expiration_time
    )

    db.add(subscribe)
    db.commit()


@router.delete("/subscription")
def unsubscribe_from_push(
        endpoint: Annotated[str, Body()],
        user: UserDep,
        db: DatabaseDep,
):
    subscription = db.scalars(
        select(PushSubscription).where(
            PushSubscription.user_id == user.id,
            PushSubscription.endpoint == endpoint
        )
    ).first()

    if subscription:
        db.delete(subscription)
        db.commit()
