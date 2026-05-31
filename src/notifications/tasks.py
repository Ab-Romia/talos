import json
import uuid
from datetime import datetime

from pywebpush import webpush_async, WebPushException
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session

from broker import broker
from config import cfg
from model import SessionLocal
from utils.datetime import utcnow
from utils.logger import get_logger
from .model import NotificationsChannel, Notification, PushSubscription, NotificationDelivery, DeliveryStatus

logger = get_logger(__name__)

_RETRYABLE_WEB_PUSH_STATUSES = {408, 425, 429, 500, 502, 503, 504}


class RetryableWebPushError(RuntimeError):
    """Raised when Taskiq should retry web push."""


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


@broker.task()
async def email(notification_id: uuid.UUID):
    logger.info(f"Processing email notification {notification_id}")
    pass


@broker.task(retry_on_error=False)
async def web_push(notification_id: uuid.UUID):
    """
    Enqueue per-subscription web-push tasks for a notification.

    Each subscription is handled by web_push_subscription which relies on Taskiq's retry mechanism.
    This removes the manual aggregation / retry counting logic from the main worker.
    """
    logger.info(f"Enqueueing web push subscription tasks for notification {notification_id}")

    with SessionLocal() as db:
        notification = db.get(Notification, notification_id)

        if not notification:
            logger.warning(f"Notification {notification_id} not found")
            return

        push_config = cfg().push
        if not push_config.vapid_private_key:
            logger.error("VAPID private key not configured")
            _update_delivery_status(db, notification_id, DeliveryStatus.FAILED)
            return

        # remove expired subscriptions
        db.execute(
            delete(PushSubscription)
            .where(PushSubscription.user_id == notification.user_id)
            .where(PushSubscription.expiration_time < utcnow())
        )

        subscriptions = db.scalars(
            select(PushSubscription).where(PushSubscription.user_id == notification.user_id)
        ).all()

        if not subscriptions:
            logger.debug(f"No push subscriptions found for user {notification.user_id}")
            _update_delivery_status(db, notification_id, DeliveryStatus.FAILED)
            return

        # Ensure there is a NotificationDelivery for PUSH and set it to PENDING
        existing_delivery = db.scalars(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == notification_id,
                NotificationDelivery.channel == NotificationsChannel.PUSH,
            )
        ).first()

        if not existing_delivery:
            db.add(NotificationDelivery(notification_id=notification_id, channel=NotificationsChannel.PUSH))
            db.commit()
        else:
            existing_delivery.status = DeliveryStatus.PENDING
            existing_delivery.sent_at = None
            db.commit()

    # Enqueue (and/or run) a per-subscription task for each subscription. Each of these
    # tasks is responsible for its own retry policy and marking the delivery as SENT.
    for subscription in subscriptions:
        try:
            # Awaiting the decorated task schedules it (and may run inline in tests);
            # Taskiq worker processes will execute these tasks in parallel in production.
            await web_push_subscription(notification_id=notification_id, subscription_id=subscription.id)
        except Exception as exc:
            logger.exception(f"Failed to enqueue/run web_push_subscription for subscription {subscription.id}: {exc}")

    logger.info(f"Enqueued {len(subscriptions)} web push subscription tasks for notification {notification_id}")


@broker.task(retry_on_error=True, max_retries=3)
async def web_push_subscription(notification_id: uuid.UUID, subscription_id: uuid.UUID):
    """
    Send web push to a single PushSubscription. Taskiq retry settings govern retry behavior.

    On success the overall NotificationDelivery (notification_id + PUSH) is marked SENT.
    On retryable failure the exception is re-raised so Taskiq retries. On permanent failure the
    subscription may be removed (e.g. 410 Gone) and the task exits.
    """
    logger.info(f"Processing web push subscription {subscription_id} for notification {notification_id}")

    with SessionLocal() as db:
        notification = db.get(Notification, notification_id)
        subscription = db.get(PushSubscription, subscription_id)

        if not notification:
            logger.warning(f"Notification {notification_id} not found")
            return

        if not subscription:
            logger.debug(f"Subscription {subscription_id} not found; skipping")
            return

        push_config = cfg().push
        if not push_config.vapid_private_key:
            logger.error("VAPID private key not configured")
            _update_delivery_status(db, notification_id, DeliveryStatus.FAILED)
            return

        try:
            await webpush_async(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": subscription.keys,
                },
                data=json.dumps({
                    "title": notification.title,
                    "body": notification.body,
                    "data": notification.data,
                }),
                vapid_private_key=push_config.vapid_private_key,
                vapid_claims={"sub": push_config.vapid_subject or "mailto:admin@example.com"},
            )
        except WebPushException as exc:
            if _is_retryable_web_push_exception(exc):
                logger.warning(f"Retryable web push error for subscription {subscription_id}: {exc}; re-raising for retry")
                raise
            else:
                logger.warning(f"Permanent web push error for subscription {subscription_id}: {exc}; skipping and possibly removing subscription")
                # If subscription is gone (410) remove it
                response = getattr(exc, "response", None)
                status = getattr(response, "status", None)
                if status == 410:
                    try:
                        db.delete(subscription)
                        db.commit()
                        logger.info(f"Removed subscription {subscription_id} due to 410 Gone")
                    except Exception:
                        logger.exception(f"Failed to remove subscription {subscription_id}")
                return
        else:
            # mark overall delivery SENT
            _update_delivery_status(db, notification_id, DeliveryStatus.SENT, sent_at=utcnow())
            logger.info(f"Successfully sent web push for subscription {subscription_id} (notification {notification_id})")


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
