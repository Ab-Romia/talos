import uuid
from typing import Annotated

from fastapi import APIRouter, Query, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy import select, delete
from starlette import status

from auth.dependencies import UserDep
from auth.model import User
from config import cfg
from database import DatabaseDep
from utils.datetime import utcnow
from .model import Notification, PushSubscription, NotificationSchema, PushSubscriptionRequest
from .service import (
    get_user_notifications,
    mark_as_read,
    get_unread_count as get_unread_count_service,
    get_unread_counts_by_channel,
    mark_channel_as_read,
)

notifications = APIRouter(prefix="/notifications", tags=["Notifications"])


@notifications.get(
    "/",
    response_model=list[NotificationSchema],
    description="""
Retrieve a paginated list of notifications for the current user.
    
- `limit`: Maximum number of notifications to return.
- `offset`: Number of notifications to skip for pagination.
- `unread_only`: If true, only return unread notifications.
- `after_notification_id`: If provided, return notifications created after the specified notification ID.
""")
def get_notifications(
        current_user: UserDep,
        db: DatabaseDep,
        limit: int = Query(20, le=100),
        offset: int = 0,
        unread_only: bool = False,
        after_notification_id: uuid.UUID | None = None
):
    return get_user_notifications(
        db=db,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
        after_notification_id=after_notification_id
    )


@notifications.post("/{notification_id}/read", description="Mark a specific notification as read.")
def mark_as_read_(notification_id: uuid.UUID, current_user: UserDep, db: DatabaseDep):
    success = mark_as_read(
        db=db,
        user_id=current_user.id,
        notification_id=notification_id,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")


@notifications.get("/unread-count", description="Get the count of unread notifications for the current user.")
def get_unread_count(db: DatabaseDep, current_user: UserDep):
    count = get_unread_count_service(
        db=db,
        user_id=current_user.id,
    )

    return {"unread_count": count}


@notifications.get("/unread-by-channel", description="Unread notification counts grouped by channel.")
def get_unread_by_channel(db: DatabaseDep, current_user: UserDep):
    return get_unread_counts_by_channel(db=db, user_id=current_user.id)


@notifications.post("/channel/{channel_id}/read", description="Mark all of a channel's notifications as read.")
def mark_channel_read(channel_id: uuid.UUID, db: DatabaseDep, current_user: UserDep):
    marked = mark_channel_as_read(db=db, user_id=current_user.id, channel_id=channel_id)
    return {"marked": marked}


class NotificationPreferences(BaseModel):
    email_notifications: bool = True


@notifications.get("/preferences", response_model=NotificationPreferences,
                   description="Get the current user's notification preferences.")
def get_preferences(current_user: UserDep):
    data = current_user.data or {}
    return NotificationPreferences(email_notifications=bool(data.get("email_notifications", True)))


@notifications.put("/preferences", response_model=NotificationPreferences,
                   description="Update the current user's notification preferences.")
def update_preferences(prefs: NotificationPreferences, current_user: UserDep, db: DatabaseDep):
    user = db.get(User, current_user.id)
    # Reassign the dict so SQLAlchemy notices the JSON change (in-place edits
    # aren't tracked).
    user.data = {**(user.data or {}), "email_notifications": prefs.email_notifications}
    db.commit()
    return prefs


@notifications.post("/read-all", description="Mark all notifications as read for the current user.")
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


@notifications.get(
    "/vapid-public-key",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "VAPID public key not configured"}},
    description="Get the VAPID public key for web push subscriptions."
)
def get_vapid_public_key():
    if not cfg().push:
        raise HTTPException(status_code=503, detail="VAPID public key not configured")
    return {"vapid_public_key": cfg().push.vapid_public_key}


@notifications.post("/subscription", status_code=status.HTTP_201_CREATED,
                    description="Subscribe to web push notifications.")
def subscribe_to_push(push_subscription: PushSubscriptionRequest, user: UserDep, db: DatabaseDep):
    # TODO: clean up expired subscriptions periodically
    # TODO: error handling
    db.add(PushSubscription(
        user_id=user.id,
        **push_subscription.model_dump()
    ))
    db.commit()


@notifications.delete(
    "/subscription",
    status_code=status.HTTP_204_NO_CONTENT,
    description="Unsubscribe from web push notifications by endpoint."
)
def unsubscribe_from_push(endpoint: Annotated[str, Body()], user: UserDep, db: DatabaseDep):
    deleted_id = db.scalar(
        delete(PushSubscription)
        .where(
            PushSubscription.user_id == user.id,
            PushSubscription.endpoint == endpoint
        ).returning(PushSubscription.id)
    )
    if deleted_id is None:
        raise HTTPException(status_code=404, detail="Subscription not found")

    db.commit()
