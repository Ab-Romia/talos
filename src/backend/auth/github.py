import os

from authlib.integrations.starlette_client import OAuth
from fastapi import Request, HTTPException, status, Response, APIRouter
from sqlalchemy import select

from model import DatabaseDep
from model.identity import IdentityProvider, Issuer, User
from .helpers import create_and_save_token

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

oauth = OAuth()

oauth.register(
    name="github",
    client_id=GITHUB_CLIENT_ID,
    client_secret=GITHUB_CLIENT_SECRET,
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "user:email"},
)

router = APIRouter()


@router.get("/github")
async def github_login(request: Request):
    redirect_uri = request.url_for("github_callback")
    return await oauth.github.authorize_redirect(request, redirect_uri)


@router.get("/github/callback")
async def github_callback(request: Request, response: Response, db: DatabaseDep):
    fail = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GitHub authentication failed")

    # TODO: handle errors (csrf)
    token = await oauth.github.authorize_access_token(request)
    if not token:
        raise fail

    resp = await oauth.github.get("user", token=token)
    if not resp or resp.status_code != 200:
        raise fail
    github_user = resp.json()

    github_id = str(github_user.get("id")) if github_user.get("id") is not None else None
    username = github_user.get("login")
    name = github_user.get("name")
    email = github_user.get("email")

    if not email:
        emails_resp = await oauth.github.get("user/emails", token=token)
        if emails_resp and emails_resp.status_code == 200:
            emails = emails_resp.json()
            primary_email = next((e for e in emails if e.get("primary")), None)
            email = primary_email.get("email") if primary_email else None

    if not github_id or not email:
        raise fail

    user = db.scalar(
        select(User)
        .join(IdentityProvider, IdentityProvider.user_id == User.id)
        .where(IdentityProvider.issuer == Issuer.github, IdentityProvider.data["sub"].as_string() == github_id)
    )

    if not user:
        # Attempt to find by primary_email and create/link if needed
        # user = db.query(User).filter(User.primary_email == email).first()

        user = User(
            username=username,
            primary_email=email,
            email_verified=True,
            name=name,
            data={},
            roles=[],
        )
        db.add(user)
        db.flush()

        identity = IdentityProvider(user_id=user.id, issuer=Issuer.github, data={"sub": github_id})
        db.add(identity)
        db.commit()

    return create_and_save_token(response=response, db=db, user_id=user.id)
