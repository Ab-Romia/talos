import uuid
from typing import Annotated, Any

import jwt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Response, status, Form
from sqlalchemy import delete, select, insert
from starlette.responses import JSONResponse

from config import cfg
from model import DatabaseDep
from model.identity import User, Issuer, IdentityProvider
from .helpers import create_and_save_token, JWTClaims, jwt_claims, _raw_user, sudo_token, UserDep

router = APIRouter()


@router.post("/create")
def generate_totp(user: UserDep):
    jwt_claims, totp = create_totp_helper(user.id)
    uri = totp.provisioning_uri(
        name=user.primary_email,
        issuer_name=cfg().app_name
    )

    # TODO: generate QR code image for URI and return as data URL
    qr_img = None

    return {
        "uri": uri,
        "jwt_totp": jwt_claims,
        "qr": qr_img
    }


@router.post("", dependencies=[Depends(sudo_token)])
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

    # Create or update the TOTP identity provider for the user
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
        response: Response,
        totp: Annotated[str, Form()],
        jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)],
        db: DatabaseDep,
):
    """
    Completion endpoint
    If the JWT required OTP to continue, it will clear that requirement and create a new session token.

    This separates state changes from the pure verification step.
    """
    totp_data = db.scalar(
        select(IdentityProvider.data)
        .where(IdentityProvider.user_id == jwt_claims.sub,
               IdentityProvider.issuer == Issuer.totp)
    )

    if not totp_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP not set up for user")

    assert "secret" in totp_data, "TOTP identity provider should always have a secret in data field"

    is_valid = pyotp.TOTP(totp_data["secret"]) \
        .verify(totp, valid_window=cfg().auth.totp_valid_window)

    if not is_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP")

    if jwt_claims.requires_otp:
        return create_and_save_token(response=response, db=db, user_id=jwt_claims.sub)

    return {"success": True, "message": "TOTP verified"}


@router.delete("")
def delete_totp(user: Annotated[User, Depends(_raw_user)], db: DatabaseDep):
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


def decode_jwt_totp_helper(jwt_totp_claims: str, user: User) -> Any:
    try:
        claims = jwt.decode(
            jwt=jwt_totp_claims,
            key=cfg().auth.jwt_secret_key,
            algorithms=[cfg().auth.jwt_algorithm],
            subject=user.id.hex,
        )
        totp_secret = claims["totp_secret"]
    except (jwt.PyJWTError, KeyError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JWT")
    return totp_secret


def create_totp_helper(sub: uuid.UUID):
    otp_base32 = pyotp.random_base32()
    totp = pyotp.totp.TOTP(otp_base32)

    jwt_claims = jwt.encode(
        payload={"sub": sub.hex, "totp_secret": otp_base32},
        key=cfg().auth.jwt_secret_key,
        algorithm=cfg().auth.jwt_algorithm,
    )
    return jwt_claims, totp
