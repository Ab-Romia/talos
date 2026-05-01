import json
import pika
from sqlalchemy.orm import Session

from modules.queue.rabbitmq import QUEUE_NAME
from modules.model.base import SessionLocal

from modules.websocket.manager import manager
import asyncio

from modules.model.notifications import (
    Notification,
    NotificationDelivery,
    NotificationsChannel
)


RABBITMQ_HOST = "localhost"

# TODO: REPLACE DICT WITH OTHER OBJECT, no broad exceptions(be specific)

def process_notification(payload: dict):

    db: Session = SessionLocal()

    try:
        notification_id = payload["notification_id"]
        channels = payload["channels"]

        notification = db.query(Notification).filter(
            Notification.id == notification_id
        ).first()

        if not notification:
            print("Notification not found")
            return

        for channel_name in channels:

            delivery = NotificationDelivery(
                notification_id=notification.id,
                channel=NotificationsChannel(channel_name),
                is_sent=True
            )

            db.add(delivery)

            print(
                f"Sent {channel_name} notification "
                f"for {notification.id}"
            )
            notify_user(notification)


        db.commit()

    except Exception as e:
        db.rollback()
        print("Worker error:", e)

    finally:
        db.close()

def notify_user(notification):
    asyncio.run(
        manager.send_to_user(
            str(notification.user_id),
            {
                "id": str(notification.id),
                "title": notification.title,
                "body": notification.body,
                "type": notification.type.value
            }
        )
    )

def callback(ch, method, properties, body):

    payload = json.loads(body)

    process_notification(payload)

    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_worker():

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=RABBITMQ_HOST)
    )

    channel = connection.channel()

    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True
    )


    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(
        queue=QUEUE_NAME,
        on_message_callback=callback
    )

    print("Waiting for notifications...")

    channel.start_consuming()

#TODO: CREATE WORKER AS BACKGROUND TASK IN FASTAPI

if __name__ == "__main__":
    start_worker()