# python
import json
import uuid

import notifications.model as model


def test_enums_have_expected_values():
    # NotificationsType members and values
    assert model.NotificationsType.message.value == "MESSAGE"
    assert model.NotificationsType.mention.value == "MENTION"
    assert model.NotificationsType.ai_complete.value == "AI_COMPLETE"
    assert model.NotificationsType.system.value == "SYSTEM"

    # NotificationsChannel members and values
    values = {c.value for c in model.NotificationChannel}
    assert values == {"IN_APP", "EMAIL", "PUSH"}


def test_preference_pydantic_models_and_serialization():
    # PreferenceUpdate should accept enum and bool
    pu = model.PreferenceUpdate(channel=model.NotificationsChannel.push, enabled=True)
    assert pu.channel is model.NotificationsChannel.push
    assert pu.enabled is True

    # PreferenceResponse should serialize enum to its value in JSON
    pr = model.PreferenceResponse(channel=model.NotificationsChannel.email, enabled=False)
    parsed = json.loads(pr.json())
    assert parsed["channel"] == model.NotificationsChannel.email.value
    assert parsed["enabled"] is False

    # Ensure Config has attribute to allow constructing from objects (sanity check)
    # (the project uses `from_attributes = True` in the model)
    assert getattr(model.PreferenceResponse.Config, "from_attributes", True) is True


def test_notification_can_be_instantiated_and_has_attributes():
    nid = uuid.uuid4()
    user_id = uuid.uuid4()
    n = model.Notification(user_id=user_id, type=model.NotificationsType.message, title="Hello", body="Body")
    # basic attributes present and types as expected
    assert hasattr(n, "id")
    assert hasattr(n, "user_id")
    assert n.user_id == user_id
    assert n.title == "Hello"
    assert n.body == "Body"
    assert isinstance(n.type, model.NotificationsType)


def test_notification_delivery_can_be_instantiated_and_has_attributes():
    delivery = model.NotificationDelivery(notification_id=uuid.uuid4(), channel=model.NotificationsChannel.email)
    assert hasattr(delivery, "notification_id")
    assert hasattr(delivery, "channel")
    assert isinstance(delivery.channel, model.NotificationsChannel)
