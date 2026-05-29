import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Enum, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model import Base
from utils.datetime import utcnow


class NotificationsType(PyEnum):
    MESSAGE = "message"
    ALERT = "alert"
    REMINDER = "reminder"
    SYSTEM = "system"


class NotificationsChannel(PyEnum):
    EMAIL = "email"
    PUSH = "push"


# worker creates
class DeliveryStatus(PyEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"),
        primary_key=True
    )

    channel: Mapped[NotificationsChannel] = mapped_column(Enum(NotificationsChannel), primary_key=True)

    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus),
        default=DeliveryStatus.PENDING,
        index=True
    )

    sent_at: Mapped[datetime | None] = mapped_column(DateTime())
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, index=True)

    notification: Mapped["Notification"] = relationship(
        "Notification",
        back_populates="deliveries"
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column()
    body: Mapped[str] = mapped_column()
    type: Mapped[NotificationsType] = mapped_column(Enum(NotificationsType), index=True)

    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default={})

    read_at: Mapped[datetime | None] = mapped_column(DateTime(), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, index=True)

    deliveries: Mapped[list["NotificationDelivery"]] = relationship(
        "NotificationDelivery",
        back_populates="notification",
        cascade="all, delete-orphan"
    )
