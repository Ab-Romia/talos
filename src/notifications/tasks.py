import os
import uuid

from pywebpush import webpush_async, WebPushException
from sqlalchemy import update, select
from starlette import status
from taskiq.message import TaskiqMessage

from broker import broker, register_callback
from config import cfg
from database import SessionLocal
from utils.datetime import utcnow
from utils.email import send_email
from utils.email_templates import notification_email
from utils.logger import get_logger
from .model import NotificationsChannel, NotificationDelivery, DeliveryStatus, NotificationSchema, \
    PushSubscriptionSchema, PushSubscription

logger = get_logger(__name__)


def _on_web_push_failed(message: TaskiqMessage, exception: Exception):
    """Callback invoked when web_push exhausts all retries. Marks delivery as FAILED."""
    notification = message.args[0] if len(message.args) > 0 else message.kwargs.get("notification")
    subscription = message.args[1] if len(message.args) > 1 else message.kwargs.get("subscription")

    assert notification is not None, "NotificationSchema argument not found in message"
    assert subscription is not None, "PushSubscriptionSchema argument not found in message"

    _mark_failed(notification.id, subscription.id)

    logger.info(f"Marked delivery as FAILED after exhausting retries"
                f" for notification {notification.id}",
                exc_info=exception)


register_callback(_on_web_push_failed)


def _mark_failed(notification_id: uuid.UUID, subscription_id: uuid.UUID | None):
    with SessionLocal() as db:
        # Mark delivery as FAILED
        db.execute(
            update(NotificationDelivery)
            .where(NotificationDelivery.notification_id == notification_id)
            .where(NotificationDelivery.subscription_id == subscription_id)
            .where(NotificationDelivery.status == DeliveryStatus.PENDING)
            .values(status=DeliveryStatus.FAILED)
        )

        # Mark subscription as deleted (soft delete) to prevent future attempts
        if subscription_id is not None:
            db.execute(
                update(PushSubscription)
                .where(PushSubscription.id == subscription_id)
                .values(deleted_at=utcnow())
            )
        db.commit()


@broker.task(retry_on_error=True, max_retries=5, delay=10,
             on_failure=_on_web_push_failed.__name__)
async def webpush(notification: NotificationSchema, subscription: PushSubscriptionSchema):
    """
    Send web push to a single PushSubscription using in-memory payloads.

    On success marks overall NotificationDelivery as SENT. On retryable failure re-raises 
    so Taskiq retries. On permanent failure removes subscription (410 Gone) or exits.
    On exhausted retries the middleware callback marks delivery as FAILED.
    """
    logger.info(f"Processing web push subscription {subscription.id} for notification {notification.id}")

    push_config = cfg().push
    assert push_config is not None

    try:
        await webpush_async(
            subscription_info=subscription.model_dump(),
            data=notification.model_dump_json(),
            vapid_private_key=push_config.vapid_private_key,
            vapid_claims={"sub": push_config.vapid_subject},
        )
    except WebPushException as exc:
        # Push Subscription is no longer valid, mark as FAILED without retrying
        if exc.response and exc.response.status in (status.HTTP_410_GONE, status.HTTP_404_NOT_FOUND):
            _mark_failed(notification.id, subscription.id)
            return
        else:
            raise  # Retry for other exceptions

    with SessionLocal() as db:
        db.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.notification_id == notification.id,
                NotificationDelivery.channel == NotificationsChannel.PUSH,
            )
            .values(status=DeliveryStatus.SENT, sent_at=(utcnow()))
        )
        db.commit()
        logger.info(f"Marked notification {notification.id} as SENT (via subscription {subscription.id})")


def _mark_email(notification_id: uuid.UUID, new_status: DeliveryStatus):
    with SessionLocal() as db:
        db.execute(
            update(NotificationDelivery)
            .where(NotificationDelivery.notification_id == notification_id)
            .where(NotificationDelivery.channel == NotificationsChannel.EMAIL)
            .where(NotificationDelivery.status == DeliveryStatus.PENDING)
            .values(status=new_status,
                    sent_at=(utcnow() if new_status == DeliveryStatus.SENT else None))
        )
        db.commit()


@broker.task(retry_on_error=True, max_retries=3, delay=15)
async def email(notification: NotificationSchema):
    """Deliver a notification by email to the recipient's primary address.

    Resolves the address from the notification's user (the schema carries no
    email) and marks the EMAIL delivery SENT on success. A missing recipient
    is a permanent failure (no retry); transport errors are swallowed by
    send_email itself, so this task treats a completed send as SENT.
    """
    from auth.model import User

    with SessionLocal() as db:
        to = db.scalar(select(User.primary_email).where(User.id == notification.user_id))

    if not to:
        _mark_email(notification.id, DeliveryStatus.FAILED)
        logger.info(f"No email address for user {notification.user_id}; marked delivery FAILED")
        return

    frontend_origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173").rstrip("/")
    data = notification.data or {}
    link = frontend_origin
    channel_id = data.get("channel_id")
    if channel_id:
        query = f"?channel={channel_id}"
        if data.get("workspace_id"):
            query += f"&workspace={data['workspace_id']}"
        if data.get("message_id"):
            query += f"&msg={data['message_id']}"
        link = f"{frontend_origin}/chat{query}"
    elif data.get("url"):
        link = f"{frontend_origin}{data['url']}"

    html, text = notification_email(notification.title, notification.body, url=link)
    await send_email(to, html, subject=notification.title, text=text)
    _mark_email(notification.id, DeliveryStatus.SENT)
    logger.info(f"Marked notification {notification.id} email delivery as SENT")
