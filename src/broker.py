from taskiq import AsyncBroker
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
)
