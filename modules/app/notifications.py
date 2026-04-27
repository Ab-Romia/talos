from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
import uuid
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any

from modules.app.notification_service import NotificationService
from modules.model.notifications import Notification ,NotificationsType

from modules.app.auth import db_dependency
from modules.app.auth import user_dependency




router = APIRouter(prefix="/notifications", tags=["Notifications"])

class NotificationResponse(BaseModel):
    id: str
    type: NotificationsType
    title: str
    body: str
    data: Optional[Dict[str, Any]]
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True #read fields directly from ORM objects

@router.get("/", response_model=list[NotificationResponse])
def get_notifications(
    limit: int = Query(20, le=100),
    offset: int = 0,
    unread_only: bool = False,
    db: Session = Depends(db_dependency),
    current_user = Depends(user_dependency),
):
    notifications = NotificationService.get_user_notifications(
        db=db,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
    )

    return notifications


@router.post("/read")
def mark_as_read(
    notification_id: uuid.UUID,
    db: Session = Depends(db_dependency),
    current_user = Depends(user_dependency),
):
    success = NotificationService.mark_as_read(
        db=db,
        notification_id=notification_id,
        user_id=current_user.id,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")

    return {"status": "ok"}


@router.get("/unread-count")
def get_unread_count(
    db: Session = Depends(db_dependency),
    current_user = Depends(user_dependency),
):
    count = NotificationService.get_unread_count(
        db=db,
        user_id=current_user.id,
    )

    return {"unread_count": count}
@router.post("/read-all")
def mark_all_as_read(
    db: Session = Depends(db_dependency),
    current_user = Depends(user_dependency),
):
    notifications = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False
    ).all()

    for n in notifications:
        n.is_read = True

    db.commit()

    return {"status": "ok"}