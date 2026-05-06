import json

import pika

RABBITMQ_HOST = "localhost"
QUEUE_NAME = "notifications"


def get_connection():
    return pika.BlockingConnection(
        pika.ConnectionParameters(host=RABBITMQ_HOST)
    )


def publish_message(message: dict):
    connection = get_connection()
    channel = connection.channel()

    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    channel.basic_publish(
        exchange="",
        routing_key=QUEUE_NAME,
        body=json.dumps(message),
        properties=pika.BasicProperties(
            delivery_mode=2,  # 🔥 make message persistent
        ),
    )

    connection.close()
