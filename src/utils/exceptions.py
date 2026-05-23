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
