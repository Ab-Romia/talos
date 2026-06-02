import uuid
from datetime import timedelta
from typing import Annotated

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status, Form
from pydantic import BaseModel
from sqlalchemy import delete, select, insert
from starlette.responses import JSONResponse

from auth.utils.helpers import sudo, UserDep, SessionDep
from auth.utils.jwt import create_token, verify_token, BaseJWTClaims
from config import cfg
from model import DatabaseDep
from utils.img import img2base64
from .model import User, Issuer, IdentityProvider

router = APIRouter()


class TOTPCreateResponse(BaseModel):
    uri: str
    jwt_totp: str
    qr: str


class TotpSetupClaims(BaseJWTClaims):
    totp_secret: str


@router.post("/create")
def generate_totp(user: UserDep):
    jwt_claims, totp = create_totp_helper(user.id)
    uri = totp.provisioning_uri(
        name=user.primary_email,
        issuer_name=cfg().app_name
    )

    qr_img = qrcode.make(uri)

    return TOTPCreateResponse(uri=uri,
                              jwt_totp=jwt_claims,
                              qr=img2base64(qr_img))


@router.post("", dependencies=[Depends(sudo)])
def register_totp(
        otp: Annotated[str, Form()],
        jwt_totp_claims: Annotated[str, Form()],
        user: UserDep,
        db: DatabaseDep,
):
    totp_secret = decode_jwt_totp_helper(jwt_totp_claims, user)

    exists = db.scalar(
        select(IdentityProvider)
        .where(IdentityProvider.user_id == user.id,
               IdentityProvider.issuer == Issuer.totp)
    )

    if exists is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="TOTP already registered for user")

    is_valid = pyotp.TOTP(totp_secret) \
        .verify(otp, valid_window=cfg().auth.totp_valid_window)

    if not is_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid TOTP")

    db.execute(
        insert(IdentityProvider)
        .values(
            user_id=user.id,
            issuer=Issuer.totp,
            data={"secret": totp_secret},
        )
    )

    db.commit()

    return {"message": "TOTP registered successfully"}


@router.post("/verify")
def verify_totp(
        totp: Annotated[str, Form()],
        session: SessionDep,
        db: DatabaseDep,
):
    """
    Completion endpoint
    If the JWT required OTP to continue, it will clear that requirement and create a new session token.

    This separates state changes from the pure verification step.
    """
    totp_data = db.scalar(
        select(IdentityProvider.data)
        .where(IdentityProvider.user_id == session.sub,
               IdentityProvider.issuer == Issuer.totp)
    )

    if not totp_data or "secret" not in totp_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP not set up for user")

    is_valid = pyotp.TOTP(totp_data["secret"]) \
        .verify(totp, valid_window=cfg().auth.totp_valid_window)

    if not is_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP")

    if session.requires_otp:
        session.requires_otp = False

    return {"success": True, "message": "TOTP verified"}


@router.delete("")
def delete_totp(user: UserDep, db: DatabaseDep):
    result = db.execute(
        delete(IdentityProvider)
        .where(IdentityProvider.user_id == user.id,
               IdentityProvider.issuer == Issuer.totp)
    )

    if result.rowcount == 0:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND,
                            content={"message": "TOTP not set up for user"})

    db.commit()
    return {"message": "TOTP cleared"}


def decode_jwt_totp_helper(jwt_totp_claims: str, user: User) -> str:
    try:
        claims = verify_token(jwt_totp_claims, return_model=TotpSetupClaims, sub=user.id)
        totp_secret = claims.totp_secret
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JWT")
    return totp_secret


def create_totp_helper(sub: uuid.UUID):
    otp_base32 = pyotp.random_base32()
    totp = pyotp.totp.TOTP(otp_base32)

    from datetime import timezone, datetime
    claims = TotpSetupClaims(
        sub=sub,
        totp_secret=otp_base32,
        exp=datetime.now(timezone.utc) + timedelta(minutes=10)
    )

    token = create_token(claims)
    return token, totp
