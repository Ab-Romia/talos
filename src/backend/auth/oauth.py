from typing import Annotated

import httpx
from authlib.integrations.base_client import MismatchingStateError
from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from fastapi import Request, HTTPException, status, Response, APIRouter
from pydantic import AfterValidator, AliasChoices, BaseModel, Field, PydanticUserError
from pydantic.functional_validators import BeforeValidator
from sqlalchemy import select
from starlette.responses import RedirectResponse

from config import cfg
from model import DatabaseDep
from model.identity import IdentityProvider, User, Issuer
from .helpers import create_and_save_token


class OAuthUserInfo(BaseModel):
    # `sub` is OIDC; GitHub uses integer `id` instead
    sub: Annotated[str, BeforeValidator(str)] = Field(validation_alias=AliasChoices("sub", "id"))
    email: str
    # GitHub doesn't supply these; defaults handle non-OIDC providers
    email_verified: bool = False
    iss: str = "https://github.com"
    name: str | None = None
    # `picture` is OIDC; GitHub uses `avatar_url`
    picture: str | None = Field(default=None, validation_alias=AliasChoices("picture", "avatar_url"))


_PROVIDERS: dict[str, dict] = {
    "google": dict(
        client_id=cfg().auth.google_client.id,
        client_secret=cfg().auth.google_client.secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    ),
    "github": dict(
        client_id=cfg().auth.github_client.id,
        client_secret=cfg().auth.github_client.secret,
        api_base_url="https://api.github.com/",
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        client_kwargs={"scope": "read:user user:email"},
    ),
}

router = APIRouter()
oauth = OAuth()

for name, opts in _PROVIDERS.items():
    oauth.register(name=name, **opts)


def invalid_provider_exception(provider):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def check_provider(provider: str):
    if provider not in _PROVIDERS.keys():
        raise invalid_provider_exception(provider)
    return provider


ProviderParam = Annotated[str, AfterValidator(check_provider)]


@router.get("/{provider}")
async def oauth_login(provider: ProviderParam, request: Request):
    client: StarletteOAuth2App = oauth.create_client(provider)

    redirect_uri = request.url_for("oauth_callback", provider=provider)
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/{provider}/callback", name="oauth_callback")
async def oauth_callback(provider: ProviderParam, request: Request, response: Response, db: DatabaseDep, ):
    client = oauth.create_client(provider)

    fail = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{provider.capitalize()} authentication failed",
    )

    # TODO: handle all errors,
    #  is this correct handling?
    try:
        token = await client.authorize_access_token(request)
    except MismatchingStateError:
        return RedirectResponse(url=request.url_for("oauth_login", provider=provider),
                                status_code=status.HTTP_302_FOUND)

    try:
        match provider:
            case "google":
                user_info = OAuthUserInfo.model_validate(
                    token["userinfo"],
                    extra="ignore"
                )
            case "github":
                res = httpx.get('https://api.github.com/user',
                                headers={"Authorization": f"Bearer {token['access_token']}"})
                user_info = OAuthUserInfo.model_validate(res.json())
            case _:
                raise invalid_provider_exception(provider)
    except PydanticUserError:
        raise fail

    identity: IdentityProvider | None = db.scalar(
        select(IdentityProvider).where(
            IdentityProvider.issuer == Issuer.oauth,
            IdentityProvider.data["sub"].as_string() == user_info.sub,
        )
    )

    if identity is not None:
        # Existing user
        return create_and_save_token(response=response, db=db, user_id=identity.user_id)

    # New Identity or new user

    user = db.scalar(
        select(User).where(User.primary_email == user_info.email)
    )
    if user is None:
        # New user
        # TODO: handle account creation -> redirect to first time profile customizations
        user = User(
            primary_email=user_info.email,
            name=user_info.name,
            username=user_info.name.replace(" ", "-").lower(),
            data={"avatar_url": user_info.picture} if user_info.picture else {},
            roles=[],
        )
        db.add(user)
        db.flush()  # populate user.id

    new_identity = IdentityProvider(
        user_id=user.id,
        issuer=Issuer.oauth,
        data={"sub": user_info.sub,
              "iss": user_info.iss, },
    )
    db.add(new_identity)
    db.commit()

    # TODO: return redirect
    token = create_and_save_token(response=response, db=db, user_id=user.id)
    # return RedirectResponse(url=request.url_for("profile"),
    #                         status_code=status.HTTP_302_FOUND)
    return token
