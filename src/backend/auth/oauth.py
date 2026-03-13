from typing import Annotated

import httpx
from authlib.integrations.base_client import MismatchingStateError
from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from fastapi import Request, HTTPException, status, Response, APIRouter
from pydantic import AfterValidator, BaseModel, PydanticUserError
from sqlalchemy import select
from starlette.responses import RedirectResponse

from src.config import cfg
from model import DatabaseDep
from model.identity import IdentityProvider, User, Issuer
from .helpers import create_and_save_token


class OIDC(BaseModel):
    sub: str
    email: str
    email_verified: bool = False
    iss: str
    name: str
    picture: str = None

    @staticmethod
    def from_github(github_user: dict):
        return OIDC(
            sub=str(github_user["id"]),
            email=github_user["email"],
            name=github_user["name"],
            picture=github_user["avatar_url"],
            iss="https://github.com"
        )


router = APIRouter()
oauth = OAuth()

for name, client in cfg().auth.oauth_clients.items():
    oauth.register(name=name, **client.model_dump())


def invalid_provider_exception(provider):
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def check_provider(provider: str):
    if provider not in cfg().auth.oauth_clients.keys():
        raise invalid_provider_exception(provider)
    return provider


ProviderParam = Annotated[str, AfterValidator(check_provider)]


@router.get("/{provider}")
async def oauth_login(provider: ProviderParam, request: Request):
    client: StarletteOAuth2App = oauth.create_client(provider)

    redirect_uri = request.url_for("oauth_callback", provider=provider)
    try:
        return await client.authorize_redirect(request, redirect_uri)
    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not connect to {provider} OAuth server"
        )


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
                user_info = OIDC.model_validate(
                    token["userinfo"],
                    extra="ignore"
                )
            case "github":
                res = httpx.get('https://api.github.com/user',
                                headers={"Authorization": f"Bearer {token['access_token']}"})
                user_info = OIDC.from_github(res.json())
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
        data=user_info.model_dump(),
    )
    db.add(new_identity)
    db.commit()

    # TODO: return redirect
    token = create_and_save_token(response=response, db=db, user_id=user.id)
    # return RedirectResponse(url=request.url_for("profile"),
    #                         status_code=status.HTTP_302_FOUND)
    return token
