import json
import uuid
from datetime import datetime

from pywebpush import webpush_async, WebPushException
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session

from broker import broker, register_callback
from config import cfg
from model import SessionLocal
from utils.datetime import utcnow
from utils.logger import get_logger
from .model import NotificationsChannel, Notification, PushSubscription, NotificationDelivery, DeliveryStatus

logger = get_logger(__name__)

_RETRYABLE_WEB_PUSH_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def _is_retryable_web_push_exception(exc: WebPushException) -> bool:
    response = getattr(exc, "response", None)
    status = getattr(response, "status", None)
    if status in _RETRYABLE_WEB_PUSH_STATUSES:
        return True

    if response is None:
        return False

    try:
        payload = response.json()
    except (TypeError, ValueError):
        return False

    errno = payload.get("errno") if isinstance(payload, dict) else None
    return errno in {0, 301, 302, 503}


async def _on_web_push_failed(retry_count: int, exception: Exception, message) -> None:
    """Callback invoked when web_push exhausts all retries. Marks delivery as FAILED."""
    try:
        # Extract notification_id from task arguments
        kwargs = message.kw
        notification = kwargs.get("notification")
        notification_id_str = notification.get("id") if notification else None

        if not notification_id_str:
            logger.warning("Could not extract notification_id from task context; skipping delivery failure update")
            return

        notification_id = uuid.UUID(notification_id_str)
        with SessionLocal() as db:
            _update_delivery_status(db, notification_id, DeliveryStatus.FAILED)
            logger.info(f"Marked delivery as FAILED after exhausting retries for notification {notification_id}")
    except Exception as exc:
        logger.exception(f"Failed to mark delivery as failed in retry callback: {exc}")


register_callback("on_web_push_failed", _on_web_push_failed)


@broker.task()
async def email(notification_id: uuid.UUID):
    logger.info(f"Processing email notification {notification_id}")
    pass


@broker.task(retry_on_error=True, max_retries=3)
async def web_push(notification: dict, subscription: dict):
    """
    Send web push to a single PushSubscription using in-memory payloads.

    On success marks overall NotificationDelivery as SENT. On retryable failure re-raises 
    so Taskiq retries. On permanent failure removes subscription (410 Gone) or exits.
    On exhausted retries the middleware callback marks delivery as FAILED.
    """
    subscription_id = subscription.get("id")
    notification_id = notification.get("id")
    logger.info(f"Processing web push subscription {subscription_id} for notification {notification_id}")

    push_config = cfg().push
    if not push_config.vapid_private_key:
        logger.error("VAPID private key not configured for web push")
        return

    try:
        await webpush_async(
            subscription_info={
                "endpoint": subscription.get("endpoint"),
                "keys": subscription.get("keys"),
            },
            data=json.dumps({
                "title": notification.get("title"),
                "body": notification.get("body"),
                "data": notification.get("data"),
            }),
            vapid_private_key=push_config.vapid_private_key,
            vapid_claims={"sub": push_config.vapid_subject or "mailto:admin@example.com"},
        )
    except WebPushException as exc:
        if _is_retryable_web_push_exception(exc):
            logger.warning(
                f"Retryable web push error for subscription {subscription_id}; re-raising for Taskiq retry: {exc}")
            raise
        else:
            logger.warning(f"Permanent web push error for subscription {subscription_id}: {exc}")
            # If subscription is gone (410) remove it from DB
            response = getattr(exc, "response", None)
            status = getattr(response, "status", None)
            if status == 410 and subscription_id:
                try:
                    with SessionLocal() as db:
                        db.execute(delete(PushSubscription).where(PushSubscription.id == uuid.UUID(subscription_id)))
                        db.commit()
                        logger.info(f"Removed subscription {subscription_id} due to 410 Gone")
                except Exception:
                    logger.exception(f"Failed to remove subscription {subscription_id}")
            return

    # mark overall delivery SENT (touch DB only on success)
    if notification_id:
        try:
            with SessionLocal() as db:
                _update_delivery_status(db, uuid.UUID(notification_id), DeliveryStatus.SENT, sent_at=utcnow())
                logger.info(f"Marked notification {notification_id} as SENT (via subscription {subscription_id})")
        except Exception:
            logger.exception(
                f"Failed to update delivery status for notification {notification_id} after successful push")


async def websocket(notification_id: uuid.UUID):
    """
    Decides whether to route via low-latency WebSocket
    or fallback to WebPush based on the current Redis state.
    """
    # Check if the user has at least one active tab open
    # The user is online. Push instantly via Socket.IO room.


def _update_delivery_status(
        db: Session,
        notification_id: uuid.UUID,
        status: DeliveryStatus,
        sent_at: datetime | None = None
) -> None:
    """Update the NotificationDelivery status for a given notification."""
    stmt = (
        update(NotificationDelivery)
        .where(
            NotificationDelivery.notification_id == notification_id,
            NotificationDelivery.channel == NotificationsChannel.PUSH,
        )
        .values(status=status)
    )
    if sent_at is not None:
        stmt = stmt.values(sent_at=sent_at)

    db.execute(stmt)
    db.commit()
