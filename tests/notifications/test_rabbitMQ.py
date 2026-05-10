# python
import json
import uuid

import pytest

import notifications.queue.rabbitmq as rabbitmq


class FakeChannel:
    def __init__(self):
        self.queue_declared = {}
        self.published = []

    def queue_declare(self, queue, durable=True):
        self.queue_declared["queue"] = queue
        self.queue_declared["durable"] = durable

    def basic_publish(self, exchange, routing_key, body, properties):
        self.published.append(
            {"exchange": exchange, "routing_key": routing_key, "body": body, "properties": properties}
        )


class FakeBlockingConnection:
    def __init__(self, params):
        # store the ConnectionParameters passed to BlockingConnection
        self.params = params
        self._channel = FakeChannel()
        self.closed = False

    def channel(self):
        return self._channel

    def close(self):
        self.closed = True


def test_get_connection_calls_blocking_connection_with_host(monkeypatch):
    created = {}

    def fake_blocking_connection(params):
        # capture the params and return a fake connection
        created["conn"] = FakeBlockingConnection(params)
        return created["conn"]

    monkeypatch.setattr(rabbitmq.pika, "BlockingConnection", fake_blocking_connection)

    conn = rabbitmq.get_connection()

    assert conn is created["conn"]
    # ensure the ConnectionParameters host matches the module constant
    assert getattr(created["conn"].params, "host", None) == rabbitmq.RABBITMQ_HOST


def test_publish_message_declares_queue_publishes_and_closes(monkeypatch):
    created = {}

    def fake_blocking_connection(params):
        inst = FakeBlockingConnection(params)
        created["inst"] = inst
        return inst

    monkeypatch.setattr(rabbitmq.pika, "BlockingConnection", fake_blocking_connection)

    payload = {"notification_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4()), "channels": ["EMAIL"]}
    rabbitmq.publish_message(payload)

    inst = created.get("inst")
    assert inst is not None, "fake connection was not created"

    chan = inst.channel()
    # queue declared with expected name and durability
    assert chan.queue_declared.get("queue") == rabbitmq.QUEUE_NAME
    assert chan.queue_declared.get("durable") is True

    # published once with correct routing key/body
    assert len(chan.published) == 1
    pub = chan.published[0]
    assert pub["exchange"] == ""
    assert pub["routing_key"] == rabbitmq.QUEUE_NAME
    assert pub["body"] == json.dumps(payload)
    # properties should indicate persistent delivery (delivery_mode == 2)
    assert getattr(pub["properties"], "delivery_mode", None) == 2

    # connection should be closed after publishing
    assert inst.closed is True
