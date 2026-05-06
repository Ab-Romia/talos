from datetime import datetime
from typing import Annotated

from fastapi import Form, HTTPException
from limits import storage, strategies
from starlette import status

from config import cfg

backend = storage.storage_from_string(cfg().cache_backend)
strategy = strategies.MovingWindowRateLimiter(backend)


# TODO: generalize limiter
def email_ratelimit(scope: str, limit: str):
    from limits import parse
    limit = parse(limit)

    def limiter(email: Annotated[str, Form()]):
        reset_time, remaining = strategy.get_window_stats(limit, scope, email)

        if strategy.hit(limit, scope, email):
            return remaining
        else:
            reset_td = datetime.fromtimestamp(reset_time) - datetime.now()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests, please try again later",
                headers={"Retry-After": str(int(reset_td.total_seconds()))}
            )

    return limiter
