"""API dependencies for dependency injection."""

from backend.api.deps.database import get_db
from backend.api.deps.auth import get_current_user, get_current_user_optional

__all__ = ["get_db", "get_current_user", "get_current_user_optional"]
