from dataclasses import dataclass
from typing import Callable, Any

from authlib.integrations.starlette_client import OAuth
from fastapi import Request, HTTPException, status, Response, APIRouter
from sqlalchemy import select

from config import config
from model.base import DatabaseDep
from model.identity import IdentityProvider, Issuer, User
from .helpers import create_and_save_token


@dataclass
class OAuthUserInfo:
    sub: str
    email: str
    name: str | None = None
    avatar_url: str | None = None


# A mapper turns raw token/userinfo dict into OAuthUserInfo
UserInfoMapper = Callable[[dict[str, Any]], OAuthUserInfo | None]


def _google_mapper(token: dict[str, Any]) -> OAuthUserInfo | None:
    info = token.get("userinfo", {})
    sub = info.get("sub")
    email = info.get("email")
    if not sub or not email:
        return None
    return OAuthUserInfo(
        sub=sub,
        email=email,
        name=info.get("name"),
        avatar_url=info.get("picture"),
    )


def _github_mapper(token: dict[str, Any]) -> OAuthUserInfo | None:
    # GitHub returns user info in the token dict directly (after userinfo fetch)
    info = token.get("userinfo", token)
    sub = str(info.get("id", ""))
    email = info.get("email")
    if not sub or not email:
        return None
    return OAuthUserInfo(
        sub=sub,
        email=email,
        name=info.get("name") or info.get("login"),
        avatar_url=info.get("avatar_url"),
    )


_PROVIDER_DEFAULTS: dict[str, dict] = {
    "google": dict(
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    ),
    "github": dict(
        api_base_url="https://api.github.com/",
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        client_kwargs={"scope": "read:user user:email"},
    ),
}

_ISSUER_MAP: dict[str, Issuer] = {
    "google": Issuer.google,
    # "github": Issuer.github,  # add when Issuer enum has github
}

_MAPPER_MAP: dict[str, UserInfoMapper] = {
    "google": _google_mapper,
    "github": _github_mapper,
}

oauth = OAuth()
cfg = config().auth

# Collect enabled providers from config
provider_clients: dict[str, Any] = {}

if cfg.google_client is not None:
    oauth.register(
        name="google",
        client_id=cfg.google_client.id,
        client_secret=cfg.google_client.secret,
        **_PROVIDER_DEFAULTS["google"],
    )
    provider_clients["google"] = oauth.google

# Example: add github when config supports it
# if cfg.github_client is not None:
#     oauth.register(
#         name="github",
#         client_id=cfg.github_client.id,
#         client_secret=cfg.github_client.secret,
#         **_PROVIDER_DEFAULTS["github"],
#     )
#     provider_clients["github"] = oauth.github

router = APIRouter()


def invalid_provider_exception(provider):
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                         detail=f"Provider '{provider}' is not configured", )


@router.get("/{provider}")
async def oauth_login(provider: str, request: Request):
    client = provider_clients.get(provider)
    if client is None:
        raise invalid_provider_exception(provider)
    redirect_uri = request.url_for("oauth_callback", provider=provider)
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/{provider}/callback", name="oauth_callback")
async def oauth_callback(provider: str, request: Request, response: Response, db: DatabaseDep, ):
    client = provider_clients.get(provider)
    if client is None:
        raise invalid_provider_exception(provider)

    mapper = _MAPPER_MAP.get(provider)
    issuer = _ISSUER_MAP.get(provider)
    if mapper is None or issuer is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Provider '{provider}' has no user-info mapper",
        )

    fail = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{provider.capitalize()} authentication failed",
    )

    token = await client.authorize_access_token(request)
    user_info = mapper(token)

    if user_info is None:
        raise fail

    # Try to find an existing identity link
    identity: IdentityProvider | None = db.scalar(
        select(IdentityProvider).where(
            IdentityProvider.issuer == issuer,
            IdentityProvider.sub == user_info.sub,
        )
    )

    if identity is not None:
        # Existing user — optionally verify email still matches
        user_id = identity.user_id
    else:
        # New user — create User + IdentityProvider in one transaction
        existing_user: User | None = db.scalar(
            select(User).where(User.primary_email == user_info.email)
        )
        if existing_user is not None:
            # Email already registered via different provider → link identity
            user = existing_user
        else:
            user = User(
                primary_email=user_info.email,
                name=user_info.name,
                avatar_url=user_info.avatar_url,
            )
            db.add(user)
            db.flush()  # populate user.id before linking

        new_identity = IdentityProvider(
            user_id=user.id,
            issuer=issuer,
            sub=user_info.sub,
        )
        db.add(new_identity)
        db.commit()
        user_id = user.id

    return create_and_save_token(response=response, db=db, user_id=user_id)
