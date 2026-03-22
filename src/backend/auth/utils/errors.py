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


class InvalidToken(AuthException):
    detail = "Invalid Token"


class SessionExpired(AuthException):
    detail = "Token has expired"


class SudoRequired(AuthException):
    detail = "Sudo mode required to access this resource"


class OTPRequired(AuthException):
    detail = "OTP verification required to access this resource"


class UserNotFound(AuthException):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "User Not Found"


class EmailNotVerified(AuthException):
    detail = "Email not verified"


class Unauthenticated(AuthException):
    detail = "No Authentication Provided"
