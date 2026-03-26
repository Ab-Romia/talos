import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Request, Depends, Header, Cookie
from pydantic import ConfigDict
from sqlalchemy import select, func, delete

from backend.auth.utils import errors, jwt
from backend.auth.utils.jwt import verify_token, BaseJWTClaims
from config import cfg
from model import DatabaseDep
from model.identity import Session
from model.utils import DATETIME

SESSION_KEY = "user_session"


class SessionClaims(BaseJWTClaims):
    model_config = ConfigDict(extra="allow")

    requires_otp: bool = False
    sudo_exp: DATETIME | None = None
    _deleted: bool = False
    _modified: bool = False
    _verify: bool = False

    def __setattr__(self, key, value):
        super().__setattr__(key, value)
        if key not in {"_deleted", "_modified"}:
            super().__setattr__("_modified", True)

    @property
    def modified(self):
        return self._modified

    @property
    def deleted(self):
        return self._deleted

    def clear(self):
        self._deleted = True


async def session_middleware(request: Request, call_next):
    response = await call_next(request)

    if "set_session" in request.state:
        claims: SessionClaims = request.state.set_session
    else:
        return response

    token = jwt.create_token(claims)
    delta = claims.exp - datetime.now(timezone.utc)

    accept_header = request.headers.get("accept", "*/*").split(",")
    if "text/html" in accept_header:
        if claims.deleted:
            response.delete_cookie(key=SESSION_KEY, path="/")
        elif claims.modified:
            response.set_cookie(
                key=SESSION_KEY,
                value=token,
                path="/",
                secure=True,
                httponly=True,
                samesite="lax",
                max_age=int(delta.total_seconds())
            )
    elif "application/json" in accept_header:
        body = response.json()
        body["session_token"] = token
        body["session_expires_at"] = claims.exp.isoformat()
        response.body = response.json_encoder.encode(body)
    else:
        response.headers["X-Session-Token"] = token

    return response


def auth_token(authorization: Annotated[str, Header()] = None,
               user_session: Annotated[str, Cookie()] = None):
    if authorization is not None:
        return (authorization
                .removeprefix("Bearer")
                .removeprefix("bearer")
                .strip())
    else:
        return user_session


def verified_session(claims: UnverifiedSessionDep, db: DatabaseDep):
    session = db.scalar(
        select(Session)
        .where(Session.id == claims.jti,
               Session.user_id == claims.sub)
    )

    if session is None:
        raise errors.SessionExpired()

    session.last_used_at = func.now()
    db.commit()

    return claims


def unverified_session(request: Request, auth_token: Annotated[str, Depends(auth_token)]):
    claims = None
    if auth_token:
        try:
            claims = verify_token(auth_token, return_model=SessionClaims)
        except errors.ExpiredToken:
            pass

    if claims is None:
        claims = SessionClaims(exp=datetime.now(timezone.utc) + cfg().auth.session_max_age)

    yield claims

    # refresh every `threshold` minutes
    last_refresh_dur = claims.exp - datetime.now(timezone.utc) - cfg().auth.session_max_age
    if last_refresh_dur < cfg().auth.session_refresh_threshold:
        claims.exp = datetime.now(timezone.utc) + cfg().auth.session_max_age

    if claims.modified or claims.deleted:
        request.state.set_session = claims


def new_session(claims: UnverifiedSessionDep, db: DatabaseDep):
    # TODO: handle existing session (e.g. revoke previous session, or allow multiple sessions per user)
    yield claims

    assert claims.sub is not None, "User ID (sub) must be set for new session"
    assert claims.jti is not None, "Session ID (jti) must be set for new session"

    sess = Session(
        id=claims.jti,
        user_id=claims.sub,
        last_used_at=func.now(),
    )
    db.add(sess)
    db.commit()


SessionDep = Annotated[SessionClaims, Depends(verified_session, scope="function")]
UnverifiedSessionDep = Annotated[SessionClaims, Depends(unverified_session, scope="function")]
NewSessionDep = Annotated[SessionClaims, Depends(new_session, scope="function")]


def revoke_session_by_id(session_id: uuid.UUID, db: DatabaseDep):
    db.execute(
        delete(Session)
        .where(Session.id == session_id)
    )
    db.commit()


def revoke_all_sessions(db: DatabaseDep, user_id: uuid.UUID, except_id: uuid.UUID = None):
    db.execute(
        delete(Session)
        .where(Session.user_id == user_id)
        .where(Session.id != except_id)
    )
    db.commit()


def get_all_sessions(db: DatabaseDep, user_id: uuid.UUID):
    return db.scalars(
        select(Session.id)
        .where(Session.user_id == user_id)
    ).all()


def get_sessions_by_uid(uid, db):
    sessions = db.scalars(
        select(Session.id, Session.last_used_at, Session.user_agent)
        .where(Session.user_id == uid)
    )

    return sessions
