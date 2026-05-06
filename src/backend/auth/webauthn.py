from datetime import timedelta
from typing import Annotated

import webauthn
from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy import insert, select, update
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.exceptions import InvalidRegistrationResponse, InvalidAuthenticationResponse
from webauthn.helpers.structs import PublicKeyCredentialDescriptor, AuthenticatorSelectionCriteria, \
    ResidentKeyRequirement

from backend.auth.utils import errors
from backend.auth.utils.helpers import sudo, UserDep
from backend.auth.utils.jwt import create_token, verify_token, BaseJWTClaims
from backend.auth.utils.session import NewSessionDep
from config import cfg
from model import DatabaseDep
from .model import Issuer, IdentityProvider

router = APIRouter()


def _rp_id() -> str:
    return cfg().app_host


def _origin() -> str:
    return cfg().app_host


class WebAuthnChallengeClaims(BaseJWTClaims):
    challenge: str


@router.post("/register/challenge", dependencies=[Depends(sudo)])
async def generate_passkey_new(user: UserDep, db: DatabaseDep):
    """
    Generate WebAuthn options for registration.

    For registration: Requires an authenticated user (the challenge must be bound to the user).
    """

    # For registration (authenticated user): generate registration options
    credentials = db.scalars(
        select(IdentityProvider.data["credential_id"])
        .where(IdentityProvider.issuer == Issuer.passkey)
        .where(IdentityProvider.user_id == user.id)
    ).all()

    credentials = [
        PublicKeyCredentialDescriptor(base64url_to_bytes(c))
        for c in credentials
    ]

    options = webauthn.generate_registration_options(
        rp_id=_rp_id(),
        rp_name=cfg().app_name,
        user_name=user.username,
        user_id=user.id.bytes[:32],  # user.id must be at most 64 bytes, according to spec
        user_display_name=user.name or user.primary_email,
        exclude_credentials=credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,  # Allows key to be discoverable
        )
    )

    from datetime import timezone, datetime

    jwt_claims = WebAuthnChallengeClaims(
        sub=user.id,
        exp=datetime.now(timezone.utc) + timedelta(minutes=1),
        challenge=bytes_to_base64url(options.challenge),
    )

    jwt_challenge = create_token(jwt_claims)

    return {
        "options": webauthn.helpers.options_to_json_dict(options),
        "jwt_challenge": jwt_challenge,
    }


@router.post("/register")
async def register_passkey(
        jwt_challenge: Annotated[str, Form()],
        credential: Annotated[str, Form()],
        name: Annotated[str, Form()],
        user: UserDep,
        db: DatabaseDep,
):
    """Verify the authenticator's registration response and persist the credential."""

    try:
        claims: WebAuthnChallengeClaims = verify_token(jwt_challenge, sub=user.id, return_model=WebAuthnChallengeClaims)
        challenge = base64url_to_bytes(claims.challenge)
    except Exception as e:
        raise errors.InvalidCredentials() from e

    try:
        verified = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=_rp_id(),
            expected_origin=_origin(),
        )
    except InvalidRegistrationResponse as e:
        raise errors.InvalidCredentials() from e

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

    return {"message": "Passkey registered successfully",
            "credential": verified.credential_id.hex()}


@router.post("/challenge")
async def generate_passkey_for_auth():
    """
    Generate WebAuthn options for authentication.

    For authentication: Unauthenticated, provide user_id to get their credentials.
    """

    # For authentication (unauthenticated): generate authentication options
    options = webauthn.generate_authentication_options(rp_id=_rp_id())

    from datetime import timezone, datetime

    jwt_claims = WebAuthnChallengeClaims(
        exp=datetime.now(timezone.utc) + timedelta(minutes=1),
        challenge=bytes_to_base64url(options.challenge),
    )

    jwt_challenge = create_token(jwt_claims)
    return {
        "options": webauthn.helpers.options_to_json_dict(options),
        "jwt_challenge": jwt_challenge,
    }


@router.post("/verify")
async def verify_passkey(
        jwt_challenge: Annotated[str, Form()],
        credential: Annotated[str, Form()],
        db: DatabaseDep,
        session: NewSessionDep,
):
    """Verify the authenticator's authentication response and issue a session token."""
    EXCEPTION = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid passkey or challenge")

    try:
        claims: WebAuthnChallengeClaims = verify_token(jwt_challenge, return_model=WebAuthnChallengeClaims)
        challenge = base64url_to_bytes(claims.challenge)
    except Exception:
        raise EXCEPTION

    # Parse the credential ID from the JSON to find the matching stored credential
    import json
    try:
        raw_id = (json.loads(credential).get("rawId")
                  or json.loads(credential).get("id"))
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

    session.sub = identity.user_id
    return {"message": "Authenticated"}
