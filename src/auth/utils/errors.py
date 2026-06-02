from typing import Iterable, TYPE_CHECKING

from fastapi import HTTPException
from starlette import status

if TYPE_CHECKING:
    from permissions.model import ScopedPermission


class AuthException(HTTPException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Authentication Error"

    def __init__(self, detail: str = None, status_code: int | None = None):
        from utils.logger import get_logger

        get_logger(__name__).debug(
            f"Raising {self.__class__.__name__}\n" +
            f"detail: {detail} and status_code: {status_code}"
        )

        super().__init__(
            status_code=status_code or self.status_code,
            detail=detail or self.detail
        )


class InvalidCredentials(AuthException):
    detail = "Invalid Credentials"


class SessionExpired(AuthException):
    detail = "Token has expired"


class SudoRequired(AuthException):
    status_code = status.HTTP_403_FORBIDDEN
    detail = "Sudo mode required to access this resource"


class OTPRequired(AuthException):
    detail = "OTP verification required to access this resource"


class UserNotFound(AuthException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "User Not Found"


class IncompleteUserProfile(AuthException):
    detail = "User profile incomplete. Please complete your profile to access this resource."


class Unauthenticated(AuthException):
    detail = "No Authentication Provided"


class ExpiredToken(AuthException):
    detail = "Authentication token has expired"


class Forbidden(AuthException):
    status_code = status.HTTP_403_FORBIDDEN
    detail = "Forbidden"

    def __init__(self, missing_perms: Iterable[ScopedPermission] | None = None, detail: str = ""):
        if missing_perms is not None:
            detail = f"""Forbidden: {detail + "\n" if detail else ""},
            Missing permissions: {', '.join(str(perm) for perm in missing_perms)}
            """
        else:
            detail = detail or self.detail

        super().__init__(detail=detail, status_code=self.status_code)
