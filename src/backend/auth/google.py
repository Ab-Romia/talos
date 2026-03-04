import os

from authlib.integrations.starlette_client import OAuth
from fastapi import Request, HTTPException, status, Response, APIRouter

from model.base import DepDB
from model.identity import IdentityProvider, Issuer, User
from .common import create_session, set_cookie_from_token

oauth = OAuth()
router = APIRouter()

oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


@router.get("/login")
async def google_login(request: Request):
    redirect_uri = request.url_for("google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/login/callback")
async def google_login_callback(request: Request, response: Response, db: DepDB):
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

    user = db.query(User) \
        .join(IdentityProvider, IdentityProvider.user_id == User.id) \
        .filter(IdentityProvider.issuer == Issuer.google, IdentityProvider.sub == google_sub) \
        .one_or_none()

    # if not user:
    #     # TODO: get user confirmation to link accounts if email already exists with password login
    #     user = db.query(User).filter(User.primary_email == email).first()
    #
    #     if not user:
    #         raise fail
    #
    #     if not user.email_verified:
    #         db.execute(update(User).where(User.id == user.id).values(email_verified=True))
    #
    #     db.add(IdentityProvider(
    #         user_id=user.id,
    #         issuer=Issuer.google,
    #         sub=google_sub
    #     ))
    #
    #     db.commit()
    set_cookie_from_token(response, token, cookie_name="access_token")

    return create_session(user.id, db)

# @google_auth.get("/signup/callback")
# @set_auth_cookie(cookie_name="access_token")
# async def google_signup_callback(request: Request, db: DepDB):
#     pass
