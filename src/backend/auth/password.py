import uuid
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, status, APIRouter, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, or_, update

from model import DatabaseDep
from model.identity import User, IdentityProvider, Issuer
from .helpers import sudo
from .session import clear_all_sessions, NewSessionDep, SessionDep

router = APIRouter()


@router.post("/")
def password_authenticate(
        form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
        db: DatabaseDep,
        session: NewSessionDep,
):
    HTTP_EXCEPTION = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                   detail="Incorrect username or password.")

    username = form_data.username
    password = form_data.password
    email = form_data.username

    # TODO: make sure there is no chance that username can be same as email of another user
    row = db.execute(
        select(User, IdentityProvider.data)
        .where(or_(User.username == username, User.primary_email == email))
        .where(IdentityProvider.user_id == User.id,
               IdentityProvider.issuer == Issuer.password)
    ).one_or_none()
    if row is None:
        raise HTTP_EXCEPTION

    user, data = row

    assert data is not None and "hash" in data, "Password identity provider should always have a data field"
    pass_hash = data["hash"]

    if (user.email_verified is False
            or user.deleted_at is not None
            or not verify_password(password, pass_hash)):
        raise HTTP_EXCEPTION

    session.sub(user.id)

    # TODO: generalize to multiple 2fa methods
    requires_otp = db.scalar(
        select(IdentityProvider)
        .where(IdentityProvider.user_id == user.id)
        .where(IdentityProvider.issuer == Issuer.totp)
    )

    if requires_otp:
        session.requires_otp()


@router.put("/change", dependencies=[Depends(sudo)])
def change_password(
        new_password: str,
        db: DatabaseDep,
        session: SessionDep
):
    db.execute(
        update(IdentityProvider)
        .where(IdentityProvider.user_id == session.sub,
               IdentityProvider.issuer == Issuer.password)
        .values(data={"hash": hash_password(new_password)})
    )

    db.commit()

    clear_all_sessions(session.sub, except_id=session.jti)


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a hashed password."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_password_identity(user_id: uuid.UUID, password: str, db: DatabaseDep):
    identity = IdentityProvider(
        user_id=user_id,
        issuer=Issuer.password,
        data={"hash": hash_password(password)},
    )

    db.add(identity)
    db.flush()

    return identity
