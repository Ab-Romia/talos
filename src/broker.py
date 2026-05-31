from taskiq import AsyncBroker, SmartRetryMiddleware, TaskiqEvents
from taskiq_redis import RedisStreamBroker, RedisAsyncResultBackend

from config import cfg

broker: AsyncBroker = (
    RedisStreamBroker(url=cfg().redis.url)
    .with_result_backend(
        RedisAsyncResultBackend(
            redis_url=cfg().redis.url,
            result_ex_time=60 * 60  # 1 hr result TTL
        )
    )
    .with_middlewares(
        SmartRetryMiddleware()
    )
)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state):
    from utils.import_sa_models import import_sa_models
    import_sa_models()
