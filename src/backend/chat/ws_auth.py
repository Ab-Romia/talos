from __future__ import annotations

import uuid

from fastapi import WebSocket
from sqlalchemy import select
from starlette import status

from backend.auth.utils.jwt import verify_token
from backend.auth.utils.session import SESSION_KEY, SessionClaims
from model.identity import Session, User

async def get_ws_user(websocket: WebSocket, db) -> User | None:
    token = websocket.cookies.get(SESSION_KEY)
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    try:
        claims = verify_token(token, return_model=SessionClaims)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    if not claims.sub or getattr(claims, "requires_otp", False):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    uid: uuid.UUID = claims.sub
    jti: uuid.UUID | None = claims.jti
    if not jti:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    user = db.scalar(
        select(User)
        .join(Session, User.id == Session.user_id)
        .where(User.id == uid)
        .where(Session.id == jti)
        .where(User.deleted_at.is_(None))
    )
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    if not user.email_verified:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    return user
