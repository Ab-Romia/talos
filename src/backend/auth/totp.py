from datetime import datetime

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Response, status, Form
from sqlalchemy.sql.annotation import Annotated

from backend.model.base import DepDB
from backend.model.identity import User, Issuer, IdentityProvider
from .common import JWTClaims, jwt_claims, _raw_user, create_session, set_cookie_from_token

router = APIRouter()

APP_NAME = "Talos"
TOTP_VALID_WINDOW = 1


@router.post("/generate")
def create_totp(user: Annotated[User, Depends(_raw_user)], db: DepDB):
    otp_base32 = pyotp.random_base32()
    uri = pyotp.totp.TOTP(otp_base32) \
        .provisioning_uri(name=user.primary_email, issuer_name=APP_NAME)

    db.add(IdentityProvider(
        user_id=user.id,
        issuer=Issuer.totp,
        sub=user.id,
        secret=otp_base32,
    ))

    db.commit()

    # return the provisioning URI so a client (or test) can present it to the user
    return {"uri": uri}


@router.post("/verify")
def complete_verification(
        response: Response,
        totp: Annotated[str, Form()],
        jwt_claims: Annotated[JWTClaims, Depends(jwt_claims)],
        db: DepDB,
):
    """
    Completion endpoint: verifies the TOTP and marks it as verified if successful.
    If the JWT required OTP to continue, it will clear that requirement and create a new session token.

    This separates state changes from the pure verification step.
    """
    totp_provider = db.query(IdentityProvider) \
        .filter(IdentityProvider.user_id == jwt_claims.sub, IdentityProvider.issuer == Issuer.totp) \
        .one_or_none()

    if not totp_provider or not getattr(totp_provider, "secret", None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP not set up for user")

    is_valid = pyotp.TOTP(totp_provider.secret).verify(totp, None, TOTP_VALID_WINDOW)

    if not is_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP")

    # mark as verified if this is the first successful verification
    if not totp_provider.verified_at:
        totp_provider.verified_at = datetime.now()
        db.commit()

    # mark JWT as no longer requiring OTP
    if jwt_claims.requires_otp:
        # create_session signature is (user_id, db, ...)
        token = create_session(jwt_claims.sub, db)
        set_cookie_from_token(response, token, cookie_name="access_token")

        return token

    return {"message": "TOTP verified"}


@router.post("/clear")
def clear_totp(user: Annotated[User, Depends(_raw_user)], db: DepDB):
    """Remove any TOTP identity providers for the current user."""
    db.query(IdentityProvider) \
        .filter(IdentityProvider.user_id == user.id, IdentityProvider.issuer == Issuer.totp) \
        .delete()
    db.commit()
    return {"message": "TOTP cleared"}
