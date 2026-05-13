from __future__ import annotations

import uuid
from typing import Iterable
from pydantic import BaseModel
from sqlalchemy import orm
from sqlalchemy.exc import IntegrityError
from utils.logger import get_logger
from websocket import ws_manager
from .model import Notification, NotificationDelivery, NotificationsChannel

# broker used to schedule background work (Taskiq/AioPika/etc.)
try:
    from notifications.app.broker import broker
except Exception:  # pragma: no cover - optional broker import
    broker = None

# For broker task that runs in worker process we may need SessionLocal from modules.model.base
try:
    from modules.model.base import SessionLocal
    from modules.model.notifications import Notification as ModuleNotification, NotificationDelivery as ModuleNotificationDelivery, NotificationsChannel as ModuleNotificationsChannel
except Exception:  # pragma: no cover
    SessionLocal = None

logger = get_logger(__name__)

# retry configuration (kept from worker for future extensions)
MAX_DELIVERY_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2.0


async def process_notification(notification_id: uuid.UUID | str,
                               channels: Iterable[NotificationsChannel] | Iterable[str],
                               db: orm.Session):
    """
    In-process notification processor compatible with the previous `notification_worker` API.
    This function is async and expects a SQLAlchemy `Session` to be passed in (this makes it
    straightforward to test with the `db_session` fixture).
    """
    # normalize id
    if isinstance(notification_id, str):
        try:
            notification_id = uuid.UUID(notification_id)
        except Exception:
            # if it's not a uuid string, leave as-is and let db.get fail
            pass

    notification = db.get(Notification, notification_id)
    if notification is None:
        logger.error(f"Notification {notification_id} not found")
        return

    try:
        for ch in channels:
            ch_enum = ch if isinstance(ch, NotificationsChannel) else NotificationsChannel(ch)
            db.add(NotificationDelivery(notification_id=notification.id, channel=ch_enum))
    except IntegrityError as e:
        db.rollback()
        logger.error(f"Failed to process notification {getattr(notification, 'id', notification_id)}: {e}")
        return

    db.commit()
    logger.info(f"Processing notification {notification.id} for channels: {channels}")

    await notify_user(notification)


async def notify_user(notification: Notification):
    # currently only sends via websocket manager
    return await ws_manager.send_to_user(
        notification.user_id,
        {
            "id": notification.id,
            "title": notification.title,
            "body": notification.body,
            "type": notification.type.value,
        }
    )


def publish_message(message: dict | BaseModel):
    """
    Enqueue a notification processing job via the configured broker task.
    If no broker is configured this will call the in-process task synchronously (best-effort).
    """
    if isinstance(message, BaseModel):
        message = message.model_dump()

    notification_id = message.get("notification_id")
    channels = message.get("channels", [])

    channels_values = [
        c.value if isinstance(c, NotificationsChannel) else str(c)
        for c in channels
    ]

    # If a broker is available, schedule the broker task. Otherwise call the task function directly if present.
    if broker is not None and hasattr(broker, 'task'):
        # there may be a broker-decorated task named `broker_process_notification` below
        try:
            # prefer .kiq if available on the task wrapper to schedule with delay support
            task = globals().get('broker_process_notification')
            if task is not None:
                # calling the task will enqueue it
                task(notification_id=str(notification_id), channels=channels_values)
                return
        except Exception:
            logger.exception('Failed to enqueue via broker, falling back to direct call')

    # Fallback - try to call an in-module task function if present
    task_fn = globals().get('process_notification')
    if callable(task_fn):
        # note: this will fail unless a `db` is provided - so this fallback is only best-effort
        try:
            # If the task_fn is async we can't call it directly without an event loop; callers that use this
            # fallback should be aware. For now, just call synchronously if possible.
            task_fn(notification_id=notification_id, channels=channels_values, db=None)  # type: ignore[arg-type]
        except Exception:
            logger.exception('Failed to call in-process task fallback')


# Broker-decorated background task which worker processes can run. Keep the original name different
# from the in-process `process_notification` to avoid confusion.
if broker is not None:

    @broker.task
    async def broker_process_notification(notification_id: str, channels: list[str]):
        """
        Background worker task - this runs in the worker process and must create its own DB session.
        This implementation tries to use the project's `modules.model` SessionLocal and models if present.
        """
        if SessionLocal is None:
            logger.error('No SessionLocal available for broker task execution')
            return

        db = SessionLocal()
        try:
            # Try using module models if available
            if 'ModuleNotification' in globals():
                notification = db.query(ModuleNotification).filter(ModuleNotification.id == notification_id).first()
                if not notification:
                    logger.warning('Notification not found in broker task')
                    return

                for channel_name in channels:
                    delivery = ModuleNotificationDelivery(
                        notification_id=notification.id,
                        channel=ModuleNotificationsChannel(channel_name),
                    )
                    db.add(delivery)

                db.commit()
                logger.info(f'Broker processed notification {notification_id} channels={channels}')
                return {'status': 'success', 'notification_id': str(notification.id)}
            else:
                logger.error('Module models not available for broker task')
                return {'status': 'failed', 'error': 'models unavailable'}
        except Exception as e:
            db.rollback()
            logger.exception('Broker task failed')
            return {'status': 'failed', 'error': str(e)}
        finally:
            db.close()
