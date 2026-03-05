from authlib.integrations.starlette_client import OAuth
from fastapi import Request, HTTPException, status, Response, APIRouter
from sqlalchemy import select

from config import config
from model.base import DatabaseDep
from model.identity import IdentityProvider, Issuer, User
from .helpers import create_and_save_token

oauth = OAuth()
router = APIRouter()

# TODO: generalize to multiple providers and dynamic registration
if config().auth.google_client is not None:
    oauth.register(
        name="google",
        client_id=config().auth.google_client.id,
        client_secret=config().auth.google_client.secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@router.get("/login")
async def google_login(request: Request):
    # TODO: generalize to multiple providers
    if not oauth.google:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                            detail="Google authentication not configured")
    redirect_uri = request.url_for("google_login_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/login/callback")
async def google_login_callback(request: Request, response: Response, db: DatabaseDep):
    fail = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google authentication failed")

    # TODO: handle errors (csrf)
    token = await oauth.google.authorize_access_token(request)

    user_info = token.get("userinfo")

    if not user_info:
        raise fail

    google_sub = user_info.get("sub")
    email = user_info.get("email")
    if not google_sub or not email:
        raise fail

    user = db.scalar(
        select(User)
        .where(User.primary_email == email)
        .where(IdentityProvider.issuer == Issuer.google, IdentityProvider.data["sub"].as_string() == google_sub)
        .where(IdentityProvider.user_id == User.id)
    )
    # TODO: handle user creation

    return create_and_save_token(response=response, db=db, user_id=user.id)

# @google_auth.get("/signup/callback")
# @set_auth_cookie(cookie_name="access_token")
# async def google_signup_callback(request: Request, db: DepDB):
#     pass
