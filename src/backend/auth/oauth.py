from typing import Annotated

import httpx
from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import Request, HTTPException, status, APIRouter
from pydantic import AfterValidator, BaseModel, PydanticUserError
from sqlalchemy import select
from starlette.responses import RedirectResponse

from model import DatabaseDep
from model.identity import IdentityProvider, User, Issuer
from config import cfg
from backend.auth.utils.session import UnverifiedSessionDep


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
                         session: UnverifiedSessionDep,
                         request: Request,
                         db: DatabaseDep):
    client = oauth.create_client(provider)

    fail = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{provider.capitalize()} authentication failed",
    )

    # TODO: handle all errors,
    #  is this correct handling?
    try:
        # authlib expects a session dict in the scope
        request.scope["session"] = session.model_extra

        token = await client.authorize_access_token(request)

        session.model_extra.clear()
        session.model_extra.update(request.session)
    except OAuthError:
        raise
        # return RedirectResponse(url=request.url_for("oauth_login", provider=provider),
        #                         status_code=status.HTTP_302_FOUND)

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

    identity = db.scalar(
        select(IdentityProvider)
        .where(
            IdentityProvider.issuer == Issuer.oauth,
            IdentityProvider.data["sub"].as_string() == user_info.sub,
        )
    )

    if identity is None:
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

        identity = IdentityProvider(
            user_id=user.id,
            issuer=Issuer.oauth,
            data=user_info.model_dump(),
        )
        db.add(identity)
        db.commit()

    session.sub = identity.user_id

    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
