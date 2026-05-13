import contextlib
import functools
import json
import uuid
from typing import Iterable

import pika
from pydantic import BaseModel
from sqlalchemy import orm
from sqlalchemy.exc import IntegrityError

from config import cfg
from utils.logger import get_logger
from websocket import ws_manager
from .model import Notification, NotificationDelivery, NotificationsChannel

logger = get_logger(__name__)


# TODO: use taskiq for task management and scheduling
#  - broker backend: RabbitMQ or Redis
#  - result backend: Redis (or database??)
#  - handle retries, failures, etc.
#    (e.g. if sending fails, retry with exponential backoff, and mark as failed after certain attempts)

# TODO: handle different channels (e.g. email, push notifications, etc.)
#  - for email, integrate with email service provider (use send_email function from utils/email.py)
#  - for push notifications, (https://pypi.org/project/pywebpush/) or external service (Firebase Cloud Messaging)
#  - for in-app notifications use websockets

async def process_notification(notification_id: uuid.UUID,
                               channels: Iterable[NotificationsChannel],
                               db: orm.Session):
    """
    Process a notification by creating delivery records and sending it to the user via websocket.
    """

    notification = db.get(Notification, notification_id)
    if notification is None:
        logger.error(f"Notification {notification_id.hex} not found")
        return

    try:
        for ch in channels:
            db.add(NotificationDelivery(notification_id=notification.id, channel=ch))
    # TODO: handle specific exceptions (e.g. notification not found, channel not supported, etc.)
    except IntegrityError as e:
        db.rollback()
        logger.error(f"Failed to process notification {notification_id.hex}: {e}")

    db.commit()
    logger.info(f"Processing notification {notification_id.hex} for channels: {channels}")

    await notify_user(notification)


async def notify_user(notification: Notification):
    # TODO: handle different channels, for now we only have push notifications via websocket
    # TODO: use model instead of dict for payload, and handle serialization properly
    notification.
    return await ws_manager.send_to_user(
        notification.user_id,
        {
            "id": notification.id,
            "title": notification.title,
            "body": notification.body,
            "type": notification.type.value
        }
    )


async def on_message_callback(ch, method, _properties, body, db):
    payload = json.loads(body)
    await process_notification(
        notification_id=uuid.UUID(payload["notification_id"]),
        channels=payload["channels"],
        db=db,
    )
    ch.basic_ack(delivery_tag=method.delivery_tag)


@contextlib.contextmanager
def notification_queue():
    from pika.adapters.asyncio_connection import AsyncioConnection
    connection = AsyncioConnection(
        pika.ConnectionParameters(host=cfg().rabbitmq.host, port=cfg().rabbitmq.port)
    )

    channel = connection.channel()

    queue = cfg().rabbitmq.notification_queue
    channel.queue_declare(queue=queue, durable=True)

    yield channel, queue

    connection.close()


def publish_message(message: dict | BaseModel):
    with notification_queue() as (channel, queue):
        if isinstance(message, BaseModel):
            message = message.model_dump()

        # TODO: use a better serialization method (e.g. protobuf)
        body = json.dumps(message)

        channel.basic_publish(
            exchange="",
            routing_key=queue,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2),
        )


def rabbitmq_available() -> bool:
    try:
        with notification_queue():
            pass
        return True
    except Exception as e:
        logger.error(f"RabbitMQ connection failed: {e}")
        return False


def start_worker(db: orm.Session):
    with notification_queue() as (channel, queue):
        on_message = functools.partial(on_message_callback, db=db)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=queue, on_message_callback=on_message)

    get_logger(__name__).info("Notification worker started, waiting for messages...")
