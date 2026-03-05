from datetime import datetime

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Response, status, Form
from sqlalchemy import insert, delete, select, update
from sqlalchemy.sql.annotation import Annotated

from config import config
from model.base import DatabaseDep
from model.identity import User, Issuer, IdentityProvider
from .common import JWTClaims, jwt_claims, _raw_user
from .helpers import create_and_save_token

router = APIRouter()


@router.post("/generate")
def create_totp(user: Annotated[User, Depends(_raw_user)], db: DatabaseDep):
    otp_base32 = pyotp.random_base32()
    uri = pyotp.totp.TOTP(otp_base32) \
        .provisioning_uri(name=user.primary_email,
                          issuer_name=config().app_name)

    db.execute(
        insert(IdentityProvider)
        .values(
            user_id=user.id,
            issuer=Issuer.totp,
            sub=user.id,
            secret=otp_base32,
        )
    )

    # return the provisioning URI so a client (or test) can present it to the user
    return {"uri": uri}


@router.post("/verify")
def complete_verification(
        response: Response,
        totp: Annotated[str, Form()],
        jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)],
        db: DatabaseDep,
):
    """
    Completion endpoint: verifies the TOTP and marks it as verified if successful.
    If the JWT required OTP to continue, it will clear that requirement and create a new session token.

    This separates state changes from the pure verification step.
    """
    totp_provider = db.scalar(
        select(IdentityProvider)
        .where(IdentityProvider.user_id == jwt_claims.sub, IdentityProvider.issuer == Issuer.totp)
    )

    if not totp_provider or not totp_provider.secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP not set up for user")

    is_valid = pyotp.TOTP(str(totp_provider.secret)) \
        .verify(totp, valid_window=config().auth.totp_valid_window)

    if not is_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP")

    # mark as verified if this is the first successful verification
    if not totp_provider.verified_at:
        db.execute(update(IdentityProvider)
                   .where(IdentityProvider.id == totp_provider.id)
                   .values(verified_at=datetime.now())
                   )
        db.commit()

    if jwt_claims.requires_otp:
        return create_and_save_token(response=response, db=db, user_id=jwt_claims.sub)

    return {"message": "TOTP verified"}


@router.post("/clear")
def clear_totp(user: Annotated[User, Depends(_raw_user)], db: DatabaseDep):
    """Remove any TOTP identity providers for the current user."""
    db.execute(
        delete(IdentityProvider)
        .where(IdentityProvider.user_id == user.id, IdentityProvider.issuer == Issuer.totp)
    )
    db.commit()
    return {"message": "TOTP cleared"}
