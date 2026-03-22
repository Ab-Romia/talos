import uuid
from typing import Annotated
from datetime import datetime, timezone

import pydantic
from fastapi import Request, Depends, Header, Cookie
from pydantic import BaseModel
from sqlalchemy import select, func, delete

from backend.auth import jwt, errors

from backend.auth.jwt import verify_token, BaseJWTClaims
from config import cfg
from model import DatabaseDep, SessionLocal
from model.identity import Session
from model.utils import DATETIME

SESSION_KEY = "user_session"


class SessionClaims(BaseJWTClaims):
    requires_otp: bool = False
    sudo_exp: DATETIME | None = None
    _modified: bool = False
    _deleted: bool = False

    def __setattr__(self, name, value):
        super().__setattr__("_modified", True)
        super().__setattr__(name, value)

    @property
    def modified(self):
        return getattr(self, "_modified", False)

    def delete(self):
        super().__setattr__("_deleted", True)


async def session_middleware(request, call_next):
    response = await call_next(request)
    if "set_session" not in request.state:
        return response

    claims = request.state.set_session

    if not claims.modified:
        return response

    accept_header = request.headers.get("accept", "text/html")

    token = jwt.create_token(claims)
    delta = claims.exp - datetime.now(timezone.utc)

    match accept_header:
        case "text/html" if claims.deleted:
            response.delete_cookie(key=SESSION_KEY, path="/")
        case "text/html":
            response.set_cookie(
                key=SESSION_KEY,
                value=token,
                path="/",
                secure=True,
                httponly=True,
                samesite="lax",
                max_age=int(delta.total_seconds())
            )
        case "application/json":
            body = response.json()
            body["session_token"] = token
            body["session_expires_at"] = claims.exp.isoformat()
            response.body = response.json_encoder.encode(body)
        case _:
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


def get_current_session(db: DatabaseDep, token):
    if token is None:
        raise errors.Unauthenticated()

    claims = verify_token(token, return_model=SessionClaims)

    session = db.scalar(
        select(Session)
        .where(Session.id == claims.jti,
               Session.user_id == claims.sub)
    )

    if session is None:
        raise errors.SessionExpired()

    return claims, session


def session(request: Request, db: DatabaseDep, auth_token: Annotated[str, Depends(auth_token)]):
    claims, session = get_current_session(db, auth_token)

    yield claims

    # refresh every `threshold` minutes
    last_refresh_dur = claims.exp - datetime.now(timezone.utc) - cfg().auth.session_max_age
    if last_refresh_dur < cfg().auth.session_refresh_threshold:
        claims.exp = datetime.now(timezone.utc) + cfg().auth.session_max_age

    session.last_used_at = func.now()
    db.commit()

    request.state.set_session = claims


class SessionBuilder(BaseModel):
    _sub: uuid.UUID = None
    _requires_otp: bool = False

    model_config = {"validate_assignment": True}

    def build(self):
        return SessionClaims(
            sub=self._sub,
            exp=datetime.now(timezone.utc) + cfg().auth.session_max_age,
            requires_otp=self._requires_otp,
        )

    def sub(self, user_id: uuid.UUID):
        self._sub = user_id
        return self

    def requires_otp(self):
        self._requires_otp = True
        return self


def new_session(request: Request, db: DatabaseDep):
    # TODO: Anonymous session

    claims_builder = SessionBuilder()

    yield claims_builder

    try:
        claims = claims_builder.build()
    except pydantic.ValidationError, pydantic.MissingError:
        return

    # clear the current session
    try:
        existing_session, session = get_current_session(db, auth_token(
            request.headers.get("authorization"),
            request.cookies.get(SESSION_KEY)
        ))
        revoke_session_by_id(existing_session.jti, db)

    except (errors.Unauthenticated, errors.SessionExpired):
        pass

    if not claims.requires_otp:
        new_session = Session(id=claims.jti,
                              user_id=claims.sub)
        db.add(new_session)
        db.commit()

    request.state.set_session = claims


SessionDep = Annotated[SessionClaims, Depends(session, scope="function")]
NewSessionDep = Annotated[SessionBuilder, Depends(new_session, scope="function")]


def revoke_session_by_id(session_id: uuid.UUID, db: DatabaseDep):
    db.execute(
        delete(Session)
        .where(Session.id == session_id)
    )
    db.commit()


def clear_all_sessions(user_id: uuid.UUID, except_id: uuid.UUID = None):
    with SessionLocal() as db:
        db.execute(
            delete(Session)
            .where(Session.user_id == user_id)
            .where(Session.id != except_id)
        )
        db.commit()
