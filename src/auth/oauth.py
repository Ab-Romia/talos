import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Annotated

import httpx
from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from fastapi import Request, HTTPException, status, APIRouter
from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from starlette.responses import RedirectResponse

from auth.model import IdentityProvider, Issuer, User, ProviderToken
from auth.utils import jwt
from auth.utils.jwt import BaseJWTClaims
from auth.utils.session import UnverifiedSessionDep, NewSessionDep, SessionDep
from utils.types import UUID as UUIDType
from config import cfg
from database import DatabaseDep
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()
oauth = OAuth()

for name, client in cfg().auth.oauth_clients.items():
    oauth.register(name=name,
                   client_secret=client.client_secret.get_secret_value(),
                   **client.model_dump(exclude="client_secret"))


class OIDC(BaseModel):
    sub: str
    email: str
    email_verified: bool = False
    iss: str
    name: str
    picture: str = None

    model_config = ConfigDict(extra="ignore")

    @staticmethod
    def from_github(github_user: dict):
        return OIDC(
            sub=str(github_user["id"]),
            email=github_user["email"],
            name=github_user["name"],
            picture=github_user["avatar_url"],
            iss="https://github.com"
        )


def _frontend(path: str) -> str:
    origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173").rstrip("/")
    return f"{origin}{path}"


def _oauth_failed(reason: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                         headers={"Location": _frontend(f"/signup?oauth_error={reason}")})


def invalid_provider_exception(provider):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                         detail=f"Invalid OAuth provider: {provider}")


def check_provider(provider: str):
    if provider not in cfg().auth.oauth_clients.keys():
        raise invalid_provider_exception(provider)
    return provider


ProviderParam = Annotated[str, AfterValidator(check_provider)]


class ConnectClaims(BaseJWTClaims):
    """Short-lived ticket authorizing a provider connection for a logged-in user."""
    user_id: UUIDType
    provider: str
    origin: str = "documents"


class _IdentityConflict(Exception):
    """The provider identity is already linked to a different account."""


# Where the OAuth callback sends the browser after a successful connect, keyed by
# the origin recorded in the ticket. Whitelisted to avoid open-redirects.
_CONNECT_REDIRECTS = {
    "documents": "/documents?drive_connected=1",
    "settings": "/settings?connected={provider}",
}


def _provider_from_iss(iss: str | None) -> str | None:
    if not iss:
        return None
    low = iss.lower()
    if "google" in low:
        return "google"
    if "github" in low:
        return "github"
    return None


@router.post("/{provider}/connect")
async def oauth_connect_ticket(provider: ProviderParam, session: SessionDep,
                               origin: str = "documents"):
    """
    Mint a ticket the SPA passes to the OAuth redirect so the resulting provider
    token is attached to the CURRENT account instead of switching identities.
    Needed because the SPA authenticates with a Bearer token while the OAuth
    browser flow only carries the cookie session (which may be a different user).
    """
    claims = ConnectClaims(
        user_id=session.sub,
        provider=provider,
        origin=origin if origin in _CONNECT_REDIRECTS else "documents",
        exp=jwt.now() + timedelta(minutes=5),
    )
    return {"ticket": claims.encode()}


@router.get("/connections")
async def oauth_connections(session: SessionDep, db: DatabaseDep):
    """Report which OAuth providers the current account is linked to."""
    connected: set[str] = set()

    for provider in db.scalars(
        select(ProviderToken.provider).where(ProviderToken.user_id == session.sub)
    ):
        connected.add(provider)

    identities = db.scalars(
        select(IdentityProvider)
        .where(IdentityProvider.user_id == session.sub)
        .where(IdentityProvider.issuer == Issuer.oauth)
        .where(IdentityProvider.deleted_at.is_(None))
    )
    for ident in identities:
        mapped = _provider_from_iss((ident.data or {}).get("iss"))
        if mapped:
            connected.add(mapped)

    return {name: (name in connected) for name in cfg().auth.oauth_clients.keys()}


@router.get("/{provider}")
async def oauth_login(provider: ProviderParam, request: Request, session: UnverifiedSessionDep,
                      connect: str | None = None):
    client = oauth.create_client(provider)

    connect_uid: uuid.UUID | None = None
    connect_origin: str = "documents"
    if connect:
        try:
            ticket = ConnectClaims.decode(connect)
            if ticket.provider != provider:
                raise ValueError("Ticket provider mismatch")
            connect_uid = ticket.user_id
            connect_origin = ticket.origin
        except Exception as e:
            logger.warning(f"OAuth {provider} connect ticket rejected: {e!r}")
            raise _oauth_failed("failed")

    extra_params = {}
    if provider == "google":
        # Ask for a refresh token so API access (Drive) survives token expiry.
        extra_params["access_type"] = "offline"
        if connect_uid is not None:
            extra_params["prompt"] = "consent"

    redirect_uri = request.url_for("oauth_callback", provider=provider)
    try:
        request.scope["session"] = {}  # authlib expects a session dict in the scope
        res = await client.authorize_redirect(request, redirect_uri, **extra_params)
        for k in [k for k in session.model_extra if k.startswith("_state_")]:
            del session.model_extra[k]
        session.model_extra.update(request.session or {})
        if connect_uid is not None:
            session.model_extra["_connect_uid"] = str(connect_uid)
            session.model_extra["_connect_origin"] = connect_origin
        session._modified = True

        return res
    except httpx.ConnectError:
        raise _oauth_failed("unavailable")


@router.get("/{provider}/callback")
async def oauth_callback(provider: ProviderParam,
                         session: NewSessionDep,
                         request: Request,
                         db: DatabaseDep):
    client: StarletteOAuth2App = oauth.create_client(provider)

    raw_connect_uid = session.model_extra.pop("_connect_uid", None)
    connect_origin = session.model_extra.pop("_connect_origin", "documents")

    try:
        # authlib expects a session dict in the scope
        request.scope["session"] = session.model_extra

        token = await client.authorize_access_token(request)

        session.model_extra.clear()
        session.model_extra.update(request.session)
    except OAuthError as e:
        logger.warning(f"OAuth {provider} token exchange failed: {e!r}; session_keys={list(session.model_extra.keys())}")
        raise _oauth_failed("failed")

    if raw_connect_uid is not None:
        # Connect flow: link the provider to the account that minted the ticket.
        # No account switching. Records an identity so the linkage is reportable
        # (and re-usable for sign-in), and persists the API token where we keep
        # one (google/Drive).
        connect_uid = uuid.UUID(raw_connect_uid)
        session.sub = connect_uid
        try:
            await _link_provider_identity(db, connect_uid, provider, client, token)
        except _IdentityConflict:
            return RedirectResponse(
                url=_frontend(f"/settings?connect_error={provider}"),
                status_code=status.HTTP_303_SEE_OTHER)
        _persist_provider_token(db, connect_uid, provider, token)
        template = _CONNECT_REDIRECTS.get(connect_origin, _CONNECT_REDIRECTS["documents"])
        return RedirectResponse(url=_frontend(template.format(provider=provider)),
                                status_code=status.HTTP_303_SEE_OTHER)

    try:
        match provider:
            case "google":
                user_info = OIDC.model_validate(token["userinfo"])
            case "github":
                res = await client.get("/user", token=token)
                user_info = OIDC.from_github(res.json())
            case _:
                raise invalid_provider_exception(provider)
    except ValidationError as e:
        logger.warning(f"OAuth {provider} profile validation failed: {e!r}")
        raise _oauth_failed("failed")

    identity = db.scalar(
        select(IdentityProvider)
        .where(IdentityProvider.issuer == Issuer.oauth)
        .where(IdentityProvider.data["sub"].as_string() == user_info.sub)
    )

    if identity is None:
        # First time login with this provider
        # Either new identity for existing user or new user
        user = db.scalar(
            select(User)
            .where(User.primary_email == user_info.email)
            .where(User.deleted_at.is_(None))
        )

        if user is None:
            base = user_info.name.replace(" ", "-").lower() or "user"
            username = base
            n = 1
            while db.scalar(select(User).where(User.username == username)):
                n += 1
                username = f"{base}-{n}"
            user = User(
                primary_email=user_info.email,
                name=user_info.name,
                username=username,
                signup_complete=True,
                data={"avatar_url": user_info.picture} if user_info.picture else {},
                roles=[],
            )
            db.add(user)
            db.flush()

        identity = IdentityProvider(
            user_id=user.id,
            issuer=Issuer.oauth,
            data=user_info.model_dump(include={"sub", "iss"})
        )
        db.add(identity)
        db.commit()
    else:
        user = db.scalar(
            select(User)
            .where(User.id == identity.user_id)
        )
        assert user is not None, "Identity exists without a user"

    session.sub = user.id

    _persist_provider_token(db, user.id, provider, token)

    return RedirectResponse(url=_frontend("/?oauth_success=1"), status_code=status.HTTP_303_SEE_OTHER)


async def _link_provider_identity(db, user_id, provider: str,
                                  client: StarletteOAuth2App, token: dict):
    """
    Record an OIDC identity for the connected provider under ``user_id`` so the
    linkage is reportable and re-usable for sign-in. Idempotent for the same
    account; raises :class:`_IdentityConflict` when the identity already belongs
    to a different account.
    """
    try:
        match provider:
            case "google":
                info = OIDC.model_validate(token["userinfo"])
            case "github":
                res = await client.get("/user", token=token)
                info = OIDC.from_github(res.json())
            case _:
                return
    except (ValidationError, KeyError):
        return

    existing = db.scalar(
        select(IdentityProvider)
        .where(IdentityProvider.issuer == Issuer.oauth)
        .where(IdentityProvider.data["sub"].as_string() == info.sub)
    )
    if existing is not None:
        if existing.user_id != user_id:
            raise _IdentityConflict()
        return

    db.add(IdentityProvider(
        user_id=user_id,
        issuer=Issuer.oauth,
        data=info.model_dump(include={"sub", "iss"}),
    ))
    db.commit()


# TODO: this should be a separate opt-in
def _persist_provider_token(db, user_id, provider: str, token: dict):
    """
    Upsert the OAuth access/refresh token returned by the provider.

    Only stores tokens we'll actually call APIs with (currently: google).
    A missing refresh_token on a re-auth is preserved from the existing row
    so we don't lose offline access if the provider only sends it on first
    consent.
    """
    if provider != "google":
        return

    access_token: str | None = token.get("access_token")
    if not access_token:
        return

    expires_at = None
    if token.get("expires_at"):
        expires_at = datetime.fromtimestamp(token["expires_at"], tz=timezone.utc)
    elif token.get("expires_in"):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token["expires_in"]))

    existing = db.scalar(
        select(ProviderToken).where(
            ProviderToken.user_id == user_id,
            ProviderToken.provider == provider,
        )
    )
    refresh_token: str | None = token.get("refresh_token") or (existing.refresh_token if existing else None)

    if existing is None:
        db.add(ProviderToken(
            user_id=user_id,
            provider=provider,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scopes=token.get("scope"),
        ))
    else:
        existing.access_token = access_token
        existing.refresh_token = refresh_token
        if expires_at is not None:
            existing.expires_at = expires_at
        existing.scopes = token.get("scope") or existing.scopes
    db.commit()
