import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Any

from pydantic import ConfigDict, BaseModel
from sqlalchemy import DateTime, ForeignKey, Enum, Uuid, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model import Base
from utils.datetime import utcnow


class NotificationSchema(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID

    title: str
    body: str
    tags: list[NotificationTag]

    data: dict[str, Any]

    read_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PushSubscriptionRequest(BaseModel):
    endpoint: str
    keys: dict[str, Any]
    expiration_time: datetime | None = None


class PushSubscriptionSchema(PushSubscriptionRequest):
    id: uuid.UUID
    user_id: uuid.UUID

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationsChannel(PyEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    PUSH = "push"


class NotificationTag(PyEnum):
    SECURITY = "security"
    ACCOUNT = "account"
    PROMOTION = "promotion"
    SOCIAL = "social"
    SYSTEM = "system"


# worker creates
class DeliveryStatus(PyEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), )

    channel: Mapped[NotificationsChannel] = mapped_column(Enum(NotificationsChannel))
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("push_subscriptions.id", ondelete="CASCADE"),
                                                              index=True)

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

    __table_args__ = (
        UniqueConstraint("notification_id", "channel", "subscription_id", name="uq_notification_delivery"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column()
    body: Mapped[str] = mapped_column()
    tags: Mapped[list[NotificationTag]] = mapped_column(ARRAY(Enum(NotificationTag)), default=[])

    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default={})

    read_at: Mapped[datetime | None] = mapped_column(DateTime(), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, index=True)

    deliveries: Mapped[list["NotificationDelivery"]] = relationship(
        "NotificationDelivery",
        back_populates="notification",
        cascade="all, delete-orphan"
    )


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    endpoint: Mapped[str] = mapped_column(index=True, unique=True)
    keys: Mapped[dict[str, Any]] = mapped_column(JSONB, default={})

    expiration_time: Mapped[datetime | None] = mapped_column(DateTime(), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, onupdate=utcnow, index=True)

    user = relationship("User", backref="push_subscriptions")
