import uuid

from broker import broker
from utils.logger import get_logger
from .model import NotificationsChannel

logger = get_logger(__name__)


@broker.task()
async def email(notification_id: uuid.UUID, channels: list[NotificationsChannel]):
    logger.info(f"Processing email notification {notification_id} for channels {channels}")
    pass


@broker.task()
async def web_push(notification_id: uuid.UUID, channels: list[NotificationsChannel]):
    logger.info(f"Processing web push notification {notification_id} for channels {channels}")
    pass
