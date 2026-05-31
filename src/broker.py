from taskiq import AsyncBroker, SmartRetryMiddleware, TaskiqEvents
from taskiq_redis import RedisStreamBroker, RedisAsyncResultBackend

from config import cfg

_callbacks_registry = {}


def register_callback(name: str, callback):
    """Register a callback by name for use in tasks."""
    _callbacks_registry[name] = callback


class SmartRetryWithCallbackMiddleware(SmartRetryMiddleware):
    async def on_error(self, message, result, exception) -> None:
        await super().on_error(message, result, exception)

        if not self.is_retry_on_error(message):
            return

        retry_count = int(message.labels.get("_retries", 0))
        max_retries = int(message.labels.get("max_retries", self.default_retry_count))

        if retry_count >= max_retries:
            callback_name = message.labels.get("retry_callback")
            if callback_name and callback_name in _callbacks_registry:
                callback = _callbacks_registry[callback_name]
                await callback(retry_count, exception, message)


broker: AsyncBroker = (
    RedisStreamBroker(url=cfg().redis.url)
    .with_result_backend(
        RedisAsyncResultBackend(
            redis_url=cfg().redis.url,
            result_ex_time=60 * 60  # 1 hr result TTL
        )
    )
    .with_middlewares(
        SmartRetryWithCallbackMiddleware()
    )
)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state):
    from utils.import_sa_models import import_sa_models
    import_sa_models()
