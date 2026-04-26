class DriveError(Exception):
    """Base exception for Drive integration."""


class DriveNotConnected(DriveError):
    """The user has not connected their Google account, or token is missing."""


class DriveTokenRefreshFailed(DriveError):
    """The stored refresh token could not be exchanged for a new access token."""


class DriveAPIError(DriveError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Drive API error {status_code}: {detail}")
