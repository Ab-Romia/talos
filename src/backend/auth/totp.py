import pyotp
from fastapi import APIRouter, Depends, HTTPException, Response, status, Form
from jose import jwt, JWTError
from sqlalchemy import delete, select, insert
from sqlalchemy.sql.annotation import Annotated

from config import config
from model.base import DatabaseDep
from model.identity import User, Issuer, IdentityProvider
from .dependencies import JWTClaims, jwt_claims, _raw_user, UserDep, sudo_token
from .helpers import create_and_save_token

router = APIRouter()


@router.post("/generate")
def generate_totp(user: Annotated[User, Depends(_raw_user)]):
    otp_base32 = pyotp.random_base32()
    uri = pyotp.totp.TOTP(otp_base32) \
        .provisioning_uri(name=user.primary_email,
                          issuer_name=config().app_name)

    jwt_claims = jwt.encode(
        {"sub": user.id, "totp_secret": otp_base32},
        key=config().auth.jwt_secret_key,
        algorithm=config().auth.jwt_algorithm,
    )

    # TODO: generate QR code image for URI and return as data URL
    qr_img = None

    return {
        "uri": uri,
        "jwt_totp": jwt_claims,
        "qr": qr_img
    }


@router.post("/register", dependencies=[Depends(sudo_token)])
def register_totp(
        user: Annotated[User, Depends(UserDep)],
        otp: str,
        jwt_totp_claims: str,
        db: DatabaseDep,
):
    """
    Endpoint to verify the TOTP for the first.
    """
    try:
        totp_secret = jwt.decode(
            jwt_totp_claims,
            key=config().auth.jwt_secret_key,
            algorithms=[config().auth.jwt_algorithm],
            subject=str(user.id)
        )["totp_secret"]
    except JWTError, KeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JWT")

    exists = db.scalar(
        select(IdentityProvider)
        .where(IdentityProvider.user_id == user.id,
               IdentityProvider.issuer == Issuer.totp)
    )

    if exists is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="TOTP already registered for user")

    is_valid = pyotp.TOTP(totp_secret) \
        .verify(otp, valid_window=config().auth.totp_valid_window)

    if not is_valid:
        return {"success": False, "message": "Invalid TOTP"}

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

    return {"success": True, "message": "TOTP registered successfully"}


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
        .verify(totp, valid_window=config().auth.totp_valid_window)

    if not is_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP")

    if jwt_claims.requires_otp:
        return create_and_save_token(response=response, db=db, user_id=jwt_claims.sub)

    return {"success": True, "message": "TOTP verified"}


@router.post("/delete")
def delete_totp(user: Annotated[User, Depends(_raw_user)], db: DatabaseDep):
    """Remove any TOTP identity providers for the current user."""
    db.execute(
        delete(IdentityProvider)
        .where(IdentityProvider.user_id == user.id,
               IdentityProvider.issuer == Issuer.totp)
    )
    db.commit()
    return {"message": "TOTP cleared"}
