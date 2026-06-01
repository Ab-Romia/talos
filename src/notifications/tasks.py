from pywebpush import webpush_async, WebPushException
from sqlalchemy import update
from starlette import status
from taskiq.message import TaskiqMessage

from broker import broker, register_callback
from config import cfg
from model import SessionLocal
from utils.datetime import utcnow
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

    _on_webpush_failed_helper(notification, subscription)

    logger.info(f"Marked delivery as FAILED after exhausting retries"
                f" for notification {notification.id}",
                exc_info=exception)


register_callback(_on_web_push_failed)


def _on_webpush_failed_helper(notification: NotificationSchema,
                              subscription: PushSubscriptionSchema):
    with SessionLocal() as db:
        # Mark delivery as FAILED
        db.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.notification_id == notification.id,
                NotificationDelivery.channel == NotificationsChannel.PUSH,
            )
            .values(status=DeliveryStatus.FAILED)
        )

        # Mark subscription as deleted (soft delete) to prevent future attempts
        db.execute(
            update(PushSubscription)
            .where(PushSubscription.id == subscription.id)
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
            _on_webpush_failed_helper(notification, subscription)
            return

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


@broker.task()
async def email(notification: NotificationSchema):
    # TODO:
    pass
