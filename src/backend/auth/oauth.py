from datetime import datetime, timezone, timedelta
from typing import Annotated

import httpx
from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from fastapi import Request, HTTPException, status, APIRouter
from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from starlette.responses import RedirectResponse

from backend.auth.model import IdentityProvider, Issuer, User, ProviderToken
from backend.auth.utils.session import UnverifiedSessionDep, NewSessionDep
from model import DatabaseDep
from src.config import cfg

router = APIRouter()
oauth = OAuth()

for name, client in cfg().auth.oauth_clients.items():
    oauth.register(name=name, **client.model_dump())


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
        session.model_extra.update(request.session or {})

        return res
    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not connect to {provider} OAuth server"
        )


@router.get("/{provider}/callback")
async def oauth_callback(provider: ProviderParam,
                         session: NewSessionDep,
                         request: Request,
                         db: DatabaseDep):
    client: StarletteOAuth2App = oauth.create_client(provider)

    fail = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{provider.capitalize()} authentication failed",
    )

    try:
        # authlib expects a session dict in the scope
        request.scope["session"] = session.model_extra

        token = await client.authorize_access_token(request)

        session.model_extra.clear()
        session.model_extra.update(request.session)
    except OAuthError:
        raise fail

    try:
        match provider:
            case "google":
                user_info = OIDC.model_validate(token["userinfo"])
            case "github":
                res = await client.get("/user", token=token)
                user_info = OIDC.from_github(res.json())
            case _:
                raise invalid_provider_exception(provider)
    except ValidationError:
        raise fail

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
            user = User(
                primary_email=user_info.email,
                name=user_info.name,
                username=user_info.name.replace(" ", "-").lower(),
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

    if not user.signup_complete:
        return RedirectResponse(url="/complete_signup", status_code=status.HTTP_303_SEE_OTHER)

    _persist_provider_token(db, user.id, provider, token)

    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


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

    access_token = token.get("access_token")
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
    refresh_token = token.get("refresh_token") or (existing.refresh_token if existing else None)

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
