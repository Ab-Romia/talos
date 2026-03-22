from fastapi import APIRouter

from backend.auth.utils.helpers import active_user
from .core import router as core_router
from .oauth import router as oauth_router
from .password import router as pass_router
from .webauthn import router as webauthn_router
from .totp import router as totp_router

auth_router = APIRouter()

auth_router.include_router(core_router)
auth_router.include_router(pass_router, prefix="/password")
auth_router.include_router(totp_router, prefix="/totp")
auth_router.include_router(oauth_router, prefix="/oauth")
auth_router.include_router(webauthn_router, prefix="/passkey")
