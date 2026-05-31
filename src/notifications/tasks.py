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
    """Raised when web push should be retried by Taskiq."""


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


@broker.task(retry_on_error=True, max_retries=3)
async def web_push(notification_id: uuid.UUID):
    """
    Send web push notifications to all subscribed users.
    
    Updates NotificationDelivery status to SENT or FAILED based on push results.
    """
    logger.info(f"Processing web push notification {notification_id}")

    with SessionLocal() as db:
        notification = db.get(Notification, notification_id)

        if not notification:
            logger.warning(f"Notification {notification_id} not found")
            return

        # TODO: verify that the notification is still relevant (e.g. not read or expired) before sending
        #  verify that not already sent

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

        notification_json = json.dumps(
            {
                "title": notification.title,
                "body": notification.body,
                "data": notification.data,
            }
        )

        sent_count = 0
        retryable_failure_count = 0
        permanent_failure_count = 0

        for subscription in subscriptions:
            try:
                await webpush_async(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": subscription.keys,
                    },
                    data=notification_json,
                    vapid_private_key=push_config.vapid_private_key,
                    vapid_claims={"sub": push_config.vapid_subject or "mailto:admin@example.com"},
                )
            except WebPushException as exc:
                if _is_retryable_web_push_exception(exc):
                    retryable_failure_count += 1
                    logger.warning(f"Retryable push failure for subscription {subscription.id}: {exc}")
                else:
                    permanent_failure_count += 1
                    logger.warning(f"Permanent push failure for subscription {subscription.id}: {exc}")
            else:
                sent_count += 1
                logger.debug(f"Successfully sent push to subscription {subscription.id}")

        if sent_count > 0:
            _update_delivery_status(db, notification_id, DeliveryStatus.SENT, sent_at=utcnow())
            logger.info(
                f"Web push delivery completed for {notification_id}: {sent_count} sent, "
                f"{retryable_failure_count} retryable failures, {permanent_failure_count} permanent failures"
            )
            return

        if retryable_failure_count > 0:
            logger.warning(f"Web push delivery for {notification_id} hit retryable failure; Taskiq will retry")
            raise RetryableWebPushError(f"web push delivery retryable for {notification_id}")

        _update_delivery_status(db, notification_id, DeliveryStatus.FAILED)
        logger.error(f"Web push delivery failed for {notification_id}: all subscriptions failed")


@broker.task
async def websocket(notification_id: uuid.UUID):
    """
    Decides whether to route via low-latency WebSocket
    or fallback to WebPush based on current Redis state.
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
