from datetime import datetime, timezone, timedelta
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, status, APIRouter, Response
from fastapi.security import OAuth2PasswordRequestForm

from model.base import DepDB
from model.identity import User, IdentityProvider, Issuer, OAuth2Token, TokenType
from .common import create_session, sudo_token, clear_all_sessions, set_cookie_from_token, active_user, create_token

router = APIRouter()


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a hashed password."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


@router.post("/")
def password_authenticate(response: Response, db: DepDB, form_data: OAuth2PasswordRequestForm = Depends()):
    username = form_data.username
    password = form_data.password
    email = form_data.username

    # TODO: make sure there is no chance that username can be same as email of another user
    res = db.query(User, IdentityProvider) \
        .filter(User.username == username or User.primary_email == email) \
        .filter(IdentityProvider.user_id == User.id,
                IdentityProvider.issuer == Issuer.password) \
        .one_or_none()

    if (not res
            or res[0].email_verified is False
            or res[0].deleted_at is not None
            or not verify_password(password, res[1].sub)):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                             detail="Incorrect username or password.")
    user = res[0]

    db.query(IdentityProvider) \
        .filter(IdentityProvider.user_id == user.id) \
        .filter(IdentityProvider.issuer != Issuer.totp) \
        .all()

    # TODO:
    requires_otp = False

    if requires_otp:
        exp = datetime.now(timezone.utc) + timedelta(minutes=5)
        access_token = create_token(
            user_id=user.id,
            requires_otp=True,
            exp=exp,
            jti=None,
        )

        token = OAuth2Token(
            access_token=access_token,
            refresh_token="",
            token_type=TokenType.bearer,
            expires_at=exp,
        )
        set_cookie_from_token(response, token, cookie_name="access_token", session_cookie=True)
        return token
    else:
        token = create_session(user.id, db=db)
        set_cookie_from_token(response, token, cookie_name="access_token")
        return token


@router.put("/change", dependencies=[Depends(sudo_token)])
def change_password(
        response: Response,
        user: Annotated[User, Depends(active_user)],
        db: DepDB,
        new_password: str,
):
    db.delete(
        db.query(IdentityProvider)
        .filter(IdentityProvider.user_id == user.id,
                IdentityProvider.issuer == Issuer.password)
    )

    db.add(IdentityProvider(
        user_id=user.id,
        issuer=Issuer.password,
        secret=hash_password(new_password)
    ))

    db.commit()

    clear_all_sessions(db, user)

    token = create_session(user_id=user.id, db=db)
    set_cookie_from_token(response, token, cookie_name="access_token")

    return token
