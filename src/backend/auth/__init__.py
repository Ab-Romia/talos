from fastapi import APIRouter

from .common import active_user, DepUser
from .common_endpoints import auth_router as sub_router
from .google import router as google_router
from .password import router

auth_router = APIRouter()
auth_router.include_router(router, prefix="/password")
auth_router.include_router(google_router, prefix="/google")
auth_router.include_router(sub_router)
