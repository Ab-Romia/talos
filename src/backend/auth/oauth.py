from datetime import datetime, timezone, timedelta
import re
from typing import Annotated
from urllib.parse import quote

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
from model.identity import Session as DBSession
from config import cfg
from backend.auth.utils import errors
from backend.auth.utils.jwt import create_oauth_handoff_token, verify_oauth_handoff_token

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


def _oauth_api_public_base() -> str:
    b = (cfg().oauth_callback_base or "").strip()
    if b:
        return b.rstrip("/")
    return f"http://{cfg().app_host}:{cfg().app_port}"


def _oauth_callback_uri(provider: str) -> str:
    return f"{_oauth_api_public_base()}/api/auth/oauth/{provider}/callback"


def _post_oauth_redirect_url(handoff: str) -> str:
    base = str(cfg().frontend_origin).rstrip("/")
    path = (cfg().frontend_post_oauth_path or "/").strip() or "/"
    if not path.startswith("/"):
        path = "/" + path
    q = f"oauth_handoff={quote(handoff, safe='')}"
    return f"{base}{path}{'&' if '?' in path else '?'}{q}"


class OAuthHandoffIn(BaseModel):
    token: str


def _unique_username_from_profile(db, email: str, name: str | None, oauth_sub: str) -> str:
    local = ""
    if email and "@" in email:
        local = email.split("@", 1)[0]
    base = re.sub(r"[^a-z0-9._-]+", "-", (local or name or f"u-{oauth_sub}").lower())
    base = re.sub(r"-{2,}", "-", base).strip("-_")[:40] or f"u-{oauth_sub[:20]}"
    candidate = base[:100]
    n = 0
    while True:
        q = select(User).where(User.username == candidate, User.deleted_at.is_(None))
        if db.scalar(q) is None:
            return candidate
        n += 1
        candidate = f"{base[:32]}-{n}"[:100]


@router.post("/handoff", status_code=status.HTTP_204_NO_CONTENT)
def oauth_session_handoff(
    body: OAuthHandoffIn,
    session: UnverifiedSessionDep,
    db: DatabaseDep,
):
    try:
        claims = verify_oauth_handoff_token(body.token)
    except errors.InvalidToken:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth handoff token",
        )
    user_id = claims.sub
    db.merge(
        DBSession(
            id=session.jti,
            user_id=user_id,
            expires_at=session.exp,
        )
    )
    db.commit()
    session.sub = user_id


@router.get("/{provider}")
async def oauth_login(provider: ProviderParam, request: Request, session: UnverifiedSessionDep):
    client = oauth.create_client(provider)

    redirect_uri = _oauth_callback_uri(provider)
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
            # New user
            # TODO: handle account creation -> redirect to first time profile customizations
            uname = _unique_username_from_profile(
                db, user_info.email, user_info.name, user_info.sub
            )
            user = User(
                primary_email=user_info.email,
                name=user_info.name,
                username=uname,
                email_verified=bool(user_info.email_verified),
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

    handoff = create_oauth_handoff_token(identity.user_id)
    return RedirectResponse(
        url=_post_oauth_redirect_url(handoff),
        status_code=status.HTTP_303_SEE_OTHER,
    )


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
