import inspect
from functools import wraps
from typing import ParamSpec, TypeVar, Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from psycopg import errors as pg_errors
from sqlalchemy import exc as sa_exc
from starlette import status

from utils.logger import get_logger


async def dbapi_error_handler(request: Request, err: sa_exc.DBAPIError):
    get_logger(__name__).exception(f"DBAPIError in {request.method} {request.url.path}: {err.orig!r}")
    orig = err.orig

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "Database error"

    match orig:
        case pg_errors.UniqueViolation():
            status_code = status.HTTP_409_CONFLICT
            message = f"{orig.diag.column_name} must be unique"
        case pg_errors.ForeignKeyViolation() | pg_errors.NotNullViolation() | pg_errors.CheckViolation() | \
             pg_errors.InvalidTextRepresentation() | pg_errors.NumericValueOutOfRange() | \
             pg_errors.StringDataRightTruncation() | pg_errors.DatatypeMismatch():
            status_code = status.HTTP_400_BAD_REQUEST
            message = "Invalid database value"
        case pg_errors.IntegrityError():
            status_code = status.HTTP_400_BAD_REQUEST
            message = "Database integrity error"
        case pg_errors.DataError():
            status_code = status.HTTP_400_BAD_REQUEST
            message = "Invalid database value"
        case pg_errors.OperationalError():
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            message = "Database unavailable"

    return JSONResponse(status_code=status_code, content={"message": message})


P = ParamSpec("P")
T = TypeVar("T")


def handle_exceptions(
        message_format: str,
        default_return: Any = None,
        log_level: str = "error",
        raise_on_error: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator to handle exceptions with formatted logging.

    Args:
        message_format: Format string for error message (can use function arg names)
        default_return: Value to return on exception
        log_level: Logging level ("error", "warning")
        raise_on_error: If True, re-raise exception after logging
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        sig = inspect.signature(func)
        is_async = inspect.iscoroutinefunction(func)

        def process_exception(e: Exception, *args: Any, **kwargs: Any) -> Any:
            """Unified exception processor for both sync and async paths."""
            logger_name = f"{func.__module__}.{func.__qualname__}"
            logger = get_logger(logger_name)

            format_dict = dict(sig.bind(*args, **kwargs).arguments)
            try:
                msg = message_format.format(**format_dict)
            except KeyError:
                msg = message_format

            getattr(logger, log_level)(msg, exc_info=e)

            if raise_on_error:
                raise e
            return default_return

        if is_async:
            @wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    return process_exception(e, *args, **kwargs)

            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    return process_exception(e, *args, **kwargs)

            return sync_wrapper

    return decorator
