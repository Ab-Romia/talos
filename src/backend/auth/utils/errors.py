from fastapi import HTTPException
from starlette import status


class AuthException(HTTPException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Authentication Error"

    def __init__(self, detail: str = None, status_code: int = None):
        super().__init__(
            status_code=status_code or self.status_code,
            detail=detail or self.detail
        )


class InvalidCredentials(AuthException):
    detail = "Invalid Credentials"


class SessionExpired(AuthException):
    detail = "Token has expired"


class SudoRequired(AuthException):
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

    def __init__(self, missing_perms: set[str] = None):
        if missing_perms:
            detail = f"Forbidden. Required permissions: {', '.join(missing_perms)}"
        else:
            detail = self.detail
        super().__init__(status_code=self.status_code, detail=detail)
