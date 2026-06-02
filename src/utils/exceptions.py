import inspect
from dataclasses import dataclass
from functools import wraps
from typing import ParamSpec, TypeVar, Any, Callable, Never

from fastapi import Request
from fastapi.responses import JSONResponse
from psycopg import errors as pg_errors
from sqlalchemy import exc as sa_exc
from starlette import status

from utils.logger import get_logger


@dataclass
class ExceptionMapper[Key, ExcT: BaseException]:
    base_exc: type[ExcT]
    responses: dict[Key, Exception | ExceptionMapper]
    default_response: Exception
    mapper: Callable[[ExcT], Key] | None = None

    def apply(self, exc: ExcT) -> Never:
        """
        Apply the error mapping to the given exception.
        If no mapper is not set, the exception class will be used as the key.
        """
        if not isinstance(exc, self.base_exc):
            raise self.default_response

        key = self.mapper(exc) if self.mapper is not None else exc.__class__
        mapped_exc = self.responses.get(key, self.default_response)

        if isinstance(mapped_exc, ExceptionMapper):
            raise mapped_exc.apply(exc)

        raise exc


async def dbapi_error_handler(request: Request, err: sa_exc.DBAPIError):
    """Generic handler for SQLAlchemy DBAPIError exceptions, mapping common PostgreSQL errors to appropriate HTTP responses."""
    get_logger(__name__).exception(f"DBAPIError in {request.method} {request.url.path}: {err.orig!r}")
    orig = err.orig

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "Internal error"

    match orig:
        case pg_errors.UniqueViolation():
            status_code = status.HTTP_409_CONFLICT
            message = "Duplicate value"
        case pg_errors.ForeignKeyViolation() | pg_errors.NotNullViolation() | pg_errors.CheckViolation() | \
             pg_errors.InvalidTextRepresentation() | pg_errors.NumericValueOutOfRange() | \
             pg_errors.StringDataRightTruncation() | pg_errors.DatatypeMismatch():
            status_code = status.HTTP_400_BAD_REQUEST
            message = "Invalid value"
        case pg_errors.IntegrityError():
            status_code = status.HTTP_400_BAD_REQUEST
            message = "Invalid value"
        case pg_errors.DataError():
            status_code = status.HTTP_400_BAD_REQUEST
            message = "Invalid value"
        case pg_errors.OperationalError():
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE

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

    :param message_format: Format string for an error message (can use function arg names)
    :param default_return: Value to return on exception
    :param log_level: Logging level ("error", "warning")
    :param raise_on_error: If True, re-raise the exception after logging
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
