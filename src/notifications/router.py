import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect, WebSocket

from backend.auth.utils.helpers import UserDep
from model import DatabaseDep
from websocket import ws_manager
from .model import NotificationsType, Notification, PreferenceResponse, PreferenceUpdate, UserNotificationPreference
from .notification_service import get_user_notifications, mark_as_read
from .preferences_service import PreferencesService

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
            is_read=notification.is_read,
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
    count = get_unread_count(
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
            Notification.is_read.is_(False)
        )
    ).all()

    for n in notifications:
        n.is_read = True

    db.commit()

    return {"status": "ok"}


@router.get("/preferences", response_model=list[PreferenceResponse])
def get_preferences(db: DatabaseDep, current_user: UserDep):
    return PreferencesService.get_preferences(db, current_user.id)


@router.put("/preferences")
def update_preferences(preferences: list[PreferenceUpdate], db: DatabaseDep, current_user: UserDep):
    PreferencesService.update_preferences(
        db,
        current_user.id,
        (
            UserNotificationPreference(
                channel=p.channel,
                enabled=p.enabled
            ) for p in preferences
        )
    )

    return {"status": "updated"}


# TODO: remove this endpoint and move WS connection logic to a separate router
@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: uuid.UUID):
    await ws_manager.connect(user_id, websocket)

    try:
        while True:
            # keep connection alive
            await websocket.receive_text()

    except WebSocketDisconnect:
        ws_manager.disconnect(user_id, websocket)
