import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, Enum, Boolean, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model import Base


class NotificationsType(PyEnum):
    mention = "MENTION"
    ai_complete = "AI_COMPLETE"
    message = "MESSAGE"
    system = "SYSTEM"


class NotificationsChannel(PyEnum):
    in_app = "IN_APP"
    email = "EMAIL"
    push = "PUSH"


# worker creates
class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"),
        index=True
    )

    channel: Mapped[NotificationsChannel] = mapped_column(Enum(NotificationsChannel))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime())
    retry_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.now, index=True)

    notification: Mapped["Notification"] = relationship(
        "Notification",
        back_populates="deliveries"
    )


# queue creates,in app reads
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[NotificationsType] = mapped_column(Enum(NotificationsType), index=True)

    title: Mapped[str] = mapped_column()
    body: Mapped[str] = mapped_column()

    data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.now, index=True)

    deliveries: Mapped[list["NotificationDelivery"]] = relationship(
        "NotificationDelivery",
        back_populates="notification",
        cascade="all, delete-orphan"
    )


class UserNotificationPreference(Base):
    __tablename__ = "user_notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True
    )

    channel: Mapped[NotificationsChannel] = mapped_column(Enum(NotificationsChannel), primary_key=True)

    enabled: Mapped[bool] = mapped_column(default=True)


class PreferenceUpdate(BaseModel):
    channel: NotificationsChannel
    enabled: bool


class PreferenceResponse(BaseModel):
    channel: NotificationsChannel
    enabled: bool

    model_config = ConfigDict(from_attributes=True)
