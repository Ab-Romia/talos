import os
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
from auth.utils.session import UnverifiedSessionDep, NewSessionDep
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


@router.get("/{provider}")
async def oauth_login(provider: ProviderParam, request: Request, session: UnverifiedSessionDep):
    client = oauth.create_client(provider)

    redirect_uri = request.url_for("oauth_callback", provider=provider)
    try:
        request.scope["session"] = {}  # authlib expects a session dict in the scope
        res = await client.authorize_redirect(request, redirect_uri)
        for k in [k for k in session.model_extra if k.startswith("_state_")]:
            del session.model_extra[k]
        session.model_extra.update(request.session or {})
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

    try:
        # authlib expects a session dict in the scope
        request.scope["session"] = session.model_extra

        token = await client.authorize_access_token(request)

        session.model_extra.clear()
        session.model_extra.update(request.session)
    except OAuthError as e:
        logger.warning(f"OAuth {provider} token exchange failed: {e!r}; session_keys={list(session.model_extra.keys())}")
        raise _oauth_failed("failed")

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
    # TODO: remove
    print(token)

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
            scope=token.get("scope"),
        ))
    else:
        existing.access_token = access_token
        existing.refresh_token = refresh_token
        if expires_at is not None:
            existing.expires_at = expires_at
        existing.scope = token.get("scope") or existing.scope
    db.commit()
