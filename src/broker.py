import inspect

from taskiq import AsyncBroker, SmartRetryMiddleware, TaskiqEvents, InMemoryBroker
from taskiq_redis import RedisStreamBroker, RedisAsyncResultBackend

from config import cfg

_callbacks_registry = {}


def register_callback(callback):
    """Register a callback function for later retrieval."""
    _callbacks_registry[callback.__name__] = callback


class SmartRetryWithCallbackMiddleware(SmartRetryMiddleware):
    """
    Add support for on_failure callbacks to SmartRetryMiddleware.
    Calls the registered callback when retries are exhausted.
    Passes retry count, exception, and message to the callback.
    """

    async def on_error(self, message, result, exception) -> None:
        retry_count = int(message.labels.get("_retries", 0)) + 1
        max_retries = int(message.labels.get("max_retries", self.default_retry_count))

        await super().on_error(message, result, exception)

        if not self.is_retry_on_error(message):
            return

        if retry_count >= max_retries:
            callback_name = message.labels.get("on_failure")
            if callback_name and callback_name in _callbacks_registry:
                callback = _callbacks_registry[callback_name]
                if callable(callback):
                    if inspect.iscoroutinefunction(callback):
                        await callback(message, exception)
                    else:
                        callback(message, exception)
                else:
                    raise ValueError(f"Registered callback '{callback_name}' is not callable")


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

if cfg().is_testing:
    broker = InMemoryBroker().with_middlewares(*broker.middlewares)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(_state):
    from utils.import_sa_models import import_sa_models
    import_sa_models()
