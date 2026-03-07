from datetime import datetime, timedelta

import jwt
import webauthn
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import insert, select, update
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.exceptions import InvalidRegistrationResponse, InvalidAuthenticationResponse

from backend.auth.dependencies import UserDep, sudo_token
from backend.auth.helpers import create_and_save_token
from config import cfg
from model import DatabaseDep
from model.identity import Issuer, IdentityProvider

router = APIRouter()


def _rp_id() -> str:
    return cfg().app_host


def _origin() -> str:
    # return config().app_origin
    return "http://localhost:8000"  # TODO: make this configurable and support https in production


@router.post("/generate")
async def generate_passkey(user: UserDep = None):
    """
    Generate WebAuthn options for either registration or authentication.

    For registration: Requires authenticated user (the challenge must be bound to the user).
    For authentication: Unauthenticated, provide user_id to get their credentials.
    """

    # Determine the user ID to use
    if user is not None:
        # For registration (authenticated user): generate registration options
        options = webauthn.generate_registration_options(
            rp_id=_rp_id(),
            rp_name=cfg().app_name,
            user_name=user.username,
            user_id=str(user.id).encode(),
            user_display_name=user.name or user.primary_email,
        )

        jwt_claims = {
            "sub": str(user.id),
            "exp": datetime.now() + timedelta(minutes=1),
            "challenge": bytes_to_base64url(options.challenge)}
    else:
        # For authentication (unauthenticated): generate authentication options
        options = webauthn.generate_authentication_options(rp_id=_rp_id())

        jwt_claims = {
            "exp": datetime.now() + timedelta(minutes=1),
            "challenge": bytes_to_base64url(options.challenge)
        }

    jwt_challenge = jwt.encode(
        payload=jwt_claims,
        key=cfg().auth.jwt_secret_key,
        algorithm=cfg().auth.jwt_algorithm,
    )
    return {
        "options": webauthn.options_to_json(options),
        "jwt_challenge": jwt_challenge,
    }


@router.post("/register", dependencies=[Depends(sudo_token)])
async def register_passkey(jwt_challenge: str,
                           credential: str,
                           name: str,
                           user: UserDep,
                           db: DatabaseDep):
    """Verify the authenticator's registration response and persist the credential."""
    # TODO: ensure single use challenge
    try:
        claims = jwt.decode(
            jwt=jwt_challenge,
            key=cfg().auth.jwt_secret_key,
            algorithms=[cfg().auth.jwt_algorithm],
            subject=str(user.id),
        )
        if claims.get("sub") != str(user.id):
            raise jwt.InvalidTokenError("Subject mismatch")
        challenge = base64url_to_bytes(claims["challenge"])
    except (jwt.PyJWTError, KeyError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid challenge token")

    try:
        verified = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=_rp_id(),
            expected_origin=_origin(),
        )
    except InvalidRegistrationResponse as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Registration failed: {e}")

    db.execute(
        insert(IdentityProvider).values(
            user_id=user.id,
            issuer=Issuer.passkey,
            data={
                "name": name,
                "credential_id": bytes_to_base64url(verified.credential_id),
                "credential_public_key": bytes_to_base64url(verified.credential_public_key),
                "sign_count": verified.sign_count,
                "device_type": verified.credential_device_type.value,
                "backed_up": verified.credential_backed_up,
            },
        )
    )
    db.commit()

    return {"success": True,
            "message": "Passkey registered successfully",
            "credential": verified.credential_id.hex()}


@router.post("/verify")
async def verify_passkey(response: Response, jwt_challenge: str, credential: str, db: DatabaseDep):
    """Verify the authenticator's authentication response and issue a session token."""
    EXCEPTION = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid passkey or challenge")

    try:
        decoded = jwt.decode(
            jwt=jwt_challenge,
            key=cfg().auth.jwt_secret_key,
            algorithms=[cfg().auth.jwt_algorithm],
        )
        challenge = base64url_to_bytes(decoded["challenge"])
    except (jwt.PyJWTError, KeyError):
        raise EXCEPTION

    # Parse the credential ID from the JSON to find the matching stored credential
    import json
    try:
        raw_id = json.loads(credential).get("rawId") or json.loads(credential).get("id")
    except (json.JSONDecodeError, AttributeError):
        raise EXCEPTION

    identity = db.scalar(
        select(IdentityProvider)
        .where(
            IdentityProvider.issuer == Issuer.passkey,
            IdentityProvider.data["credential_id"].as_string() == raw_id,
        )
    )

    if identity is None or not identity.data:
        raise EXCEPTION

    try:
        verification = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=_rp_id(),
            expected_origin=_origin(),
            credential_public_key=base64url_to_bytes(identity.data["credential_public_key"]),
            credential_current_sign_count=identity.data["sign_count"],
        )
    except InvalidAuthenticationResponse:
        raise EXCEPTION

    # Update sign count to defend against cloned authenticators
    db.execute(
        update(IdentityProvider)
        .where(IdentityProvider.id == identity.id)
        .values(data={**identity.data, "sign_count": verification.new_sign_count})
    )
    db.commit()

    return create_and_save_token(response=response, db=db, user_id=identity.user_id)
