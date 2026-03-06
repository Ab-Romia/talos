from fastapi import APIRouter

from backend.auth import google
from .core import router as core_router
from .google import router as google_router  # TODO: replace with oauth router
# from .oauth import router as oauth_router
from .password import router as pass_router

auth_router = APIRouter()
auth_router.include_router(pass_router, prefix="/password")
auth_router.include_router(google_router, prefix="/google")
auth_router.include_router(core_router)
