"""
Async utility functions for the RAG system.

Provides helpers for running async code, retrying operations,
and managing concurrency.
"""

import asyncio
import functools
import time
from typing import Any, Awaitable, Callable, List, Optional, TypeVar

T = TypeVar("T")


def run_async(coro: Awaitable[T]) -> T:
    """
    Run an async coroutine synchronously.

    Handles the case where an event loop may or may not already be running.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, create one
        return asyncio.run(coro)

    # Loop is running, use nest_asyncio pattern or run in executor
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


def async_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
):
    """
    Decorator for retrying async functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff
        retryable_exceptions: Tuple of exceptions to retry on
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        break

                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay,
                    )
                    await asyncio.sleep(delay)

            raise last_exception  # type: ignore

        return wrapper

    return decorator


def sync_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
):
    """
    Decorator for retrying sync functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff
        retryable_exceptions: Tuple of exceptions to retry on
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        break

                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay,
                    )
                    time.sleep(delay)

            raise last_exception  # type: ignore

        return wrapper

    return decorator


async def gather_with_concurrency(
    tasks: List[Awaitable[T]],
    max_concurrent: int = 10,
    return_exceptions: bool = False,
) -> List[T]:
    """
    Run async tasks with limited concurrency.

    Args:
        tasks: List of awaitable tasks
        max_concurrent: Maximum number of concurrent tasks
        return_exceptions: Whether to return exceptions instead of raising

    Returns:
        List of results in the same order as input tasks
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def bounded_task(task: Awaitable[T]) -> T:
        async with semaphore:
            return await task

    bounded_tasks = [bounded_task(task) for task in tasks]
    return await asyncio.gather(*bounded_tasks, return_exceptions=return_exceptions)


class RateLimiter:
    """
    Token bucket rate limiter for API calls.

    Limits the rate of operations to prevent hitting rate limits.
    """

    def __init__(
        self,
        rate: float,
        burst: int = 1,
    ):
        """
        Initialize rate limiter.

        Args:
            rate: Operations per second allowed
            burst: Maximum burst size
        """
        self.rate = rate
        self.burst = burst
        self._tokens = burst
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire permission to proceed (blocks if rate limited)."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            self._tokens = min(
                self.burst,
                self._tokens + elapsed * self.rate,
            )
            self._last_update = now

            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self.rate
                await asyncio.sleep(wait_time)
                self._tokens = 0
            else:
                self._tokens -= 1


class Timeout:
    """Context manager for timeouts on sync/async operations."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self._deadline: Optional[float] = None

    def __enter__(self) -> "Timeout":
        self._deadline = time.monotonic() + self.seconds
        return self

    def __exit__(self, *args) -> None:
        pass

    async def __aenter__(self) -> "Timeout":
        return self

    async def __aexit__(self, *args) -> None:
        pass

    def remaining(self) -> float:
        """Get remaining time in seconds."""
        if self._deadline is None:
            return self.seconds
        return max(0, self._deadline - time.monotonic())

    def expired(self) -> bool:
        """Check if timeout has expired."""
        if self._deadline is None:
            return False
        return time.monotonic() >= self._deadline


def timed(func: Callable[..., T]) -> Callable[..., tuple[T, float]]:
    """
    Decorator to measure function execution time.

    Returns tuple of (result, elapsed_ms).
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> tuple[T, float]:
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return result, elapsed_ms

    return wrapper


def async_timed(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[tuple[T, float]]]:
    """
    Decorator to measure async function execution time.

    Returns tuple of (result, elapsed_ms).
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs) -> tuple[T, float]:
        start = time.perf_counter()
        result = await func(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return result, elapsed_ms

    return wrapper
