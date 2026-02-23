import os
from datetime import timedelta, datetime, timezone
from typing import Annotated
from dotenv import load_dotenv

import bcrypt
import fastapi
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from authlib.integrations.starlette_client import OAuth

from pydantic import BaseModel
from starlette import status

from starlette.middleware.sessions import SessionMiddleware

from modules.model.identity import User, UserPassword,IdentityProvider, AuthUrl
import uuid
from modules.model.base import db_dependency

# TODO:
#  cookies,
#  refresh tokens,
#  sessions,
#  identity providers other than password
#  password reset,
#  logout,

load_dotenv()

auth = fastapi.APIRouter(prefix='/api/auth')

# TODO: move to config
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY').encode('utf-8')
JWT_ALGORITHM = 'HS256'
oauth2_bearer = OAuth2PasswordBearer(tokenUrl='/api/auth/token')

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

oauth = OAuth()

oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile"
    }
)

oauth.register(
    name="github",
    client_id=GITHUB_CLIENT_ID,
    client_secret=GITHUB_CLIENT_SECRET,
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "user:email"},
)


class CreateUserRequest(BaseModel):
    username: str
    primary_email: str
    password: str
    name: str


class Token(BaseModel):
    access_token: str
    token_type: str


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a hashed password."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def authenticate_user(username: str, password: str, db: db_dependency) -> bool | User:
    user = db.query(User).filter(User.username == username).first()
    if not user \
            or user.email_verified is False \
            or user.deleted_at is not None:
        return False

    # TODO: check for identity providers other than password

    user_password = db.query(UserPassword) \
        .filter(UserPassword.user_id == user.id) \
        .first()

    if not user_password:
        return False

    if not verify_password(password, str(user_password.hashed_password)):
        return False

    return user


def create_access_token(username: str, user_id: int, expires_delta: timedelta):
    encode = {'sub': username, 'id': str(user_id)}
    expires = datetime.now(timezone.utc) + expires_delta
    encode.update({'exp': expires})
    return jwt.encode(encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload["sub"]
    except JWTError:
        return None


async def get_current_user(token: Annotated[str, Depends(oauth2_bearer)]):
    """
    Validate JWT token and return current user info
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username: str = payload.get('sub')
        user_id: int = payload.get('id')
        if user_id is None or username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='could not validate user.')
        return {'username': username, 'id': user_id}
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='could not validate user.')


user_dependency = Annotated[dict, Depends(get_current_user)]
@auth.get("/google")
async def google_login(request: fastapi.Request):
    redirect_uri = request.url_for("google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@auth.get("/github")
async def github_login(request: fastapi.Request):
    redirect_uri = request.url_for("github_callback")
    return await oauth.github.authorize_redirect(request, redirect_uri)
@auth.get("/google/callback")
async def google_callback(
        request: fastapi.Request,
        db: db_dependency
):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo")

    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google authentication failed"
        )

    google_sub = user_info["sub"]
    email = user_info["email"]
    name = user_info.get("name")

    identity = db.query(IdentityProvider).filter(
        IdentityProvider.auth_url == AuthUrl.google,
        IdentityProvider.sub == google_sub
    ).first()

    if identity:
        user = db.query(User).filter(User.id == identity.user_id).first()

    else:
        user = db.query(User).filter(User.primary_email == email).first()

        if not user:
            user = User(
                username=email,
                primary_email=email,
                email_verified=True,
                name=name,
                data={},
                roles=[]
            )
            db.add(user)
            db.flush()

        identity = IdentityProvider(
            user_id=user.id,
            auth_url=AuthUrl.google,
            sub=google_sub
        )
        db.add(identity)

        db.commit()
    access_token = create_access_token(
        username=user.username,
        user_id=user.id,
        expires_delta=timedelta(minutes=20)
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }

@auth.get("/github/callback")
async def github_callback(
        request: fastapi.Request,
        db: db_dependency
):
    token = await oauth.github.authorize_access_token(request)

    resp = await oauth.github.get("user", token=token)
    github_user = resp.json()

    github_id = str(github_user["id"])
    username = github_user["login"]
    name = github_user.get("name")

    email = github_user.get("email")

    if not email:
        emails_resp = await oauth.github.get("user/emails", token=token)
        emails = emails_resp.json()
        primary_email = next((e for e in emails if e["primary"]), None)
        email = primary_email["email"] if primary_email else None

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub email not available"
        )

    identity = db.query(IdentityProvider).filter(
        IdentityProvider.auth_url == AuthUrl.github,
        IdentityProvider.sub == github_id
    ).first()

    if identity:
        user = db.query(User).filter(User.id == identity.user_id).first()

    else:
        user = db.query(User).filter(User.primary_email == email).first()

        if not user:
            user = User(
                username=username,
                primary_email=email,
                email_verified=True,
                name=name,
                data={},
                roles=[]
            )
            db.add(user)
            db.flush()

        identity = IdentityProvider(
            user_id=user.id,
            auth_url=AuthUrl.github,
            sub=github_id
        )
        db.add(identity)

        db.commit()

    access_token = create_access_token(
        username=user.username,
        user_id=user.id,
        expires_delta=timedelta(minutes=20)
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }
@auth.post('/sudo_token', response_model=Token)
async def login_for_sudo_token(user: user_dependency, form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
                               db: db_dependency):
    sudo_user = authenticate_user(user.get('username'), form_data.password, db)
    if not sudo_user or not user or sudo_user.id != user.get('id'):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='could not validate user.')
        # return 'Failed Authentication'

    token = create_access_token(sudo_user.username, sudo_user.id, timedelta(minutes=5))

    return {'access_token': token, 'token_type': 'bearer'}


@auth.put('/change_password', status_code=status.HTTP_200_OK)
def password_reset(user: user_dependency, sudo: Annotated[dict, Depends(login_for_sudo_token)],
                   db: db_dependency, current_password: str, new_password: str):
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='could not validate user.')
    current_userpassword = db.query(UserPassword).filter(UserPassword.user_id == user.get('id')).first()

    if not verify_password(current_password, current_userpassword.hashed_password):
        raise HTTPException(status_code=status.HTTP_406_NOT_ACCEPTABLE, detail='password not correct')

    current_userpassword.hashed_password = hash_password(new_password)

    return {'username': user.get('username'), 'password': new_password}


@auth.post('/signup', status_code=status.HTTP_201_CREATED)
async def CreateUser(db: db_dependency,
                     create_user: CreateUserRequest):
    create_user_model = User(
        username=create_user.username,
        primary_email=create_user.primary_email,
        email_verified=True,  # TODO: add email verification flow
        name=create_user.name,
        data={},
        roles=[]
    )
    db.add(create_user_model)

    db.flush()  # get the id before commit

    # TODO: handle exceptions for duplicate usernames/emails
    # TODO: handle different identity providers

    create_password = UserPassword(
        user_id=create_user_model.id,
        hashed_password=hash_password(create_user.password),
    )
    db.add(create_password)

    db.commit()


@auth.post('/token', response_model=Token)
async def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
                                 db: db_dependency):
    user = authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='could not validate user.')
        # return 'Failed Authentication'

    token = create_access_token(user.username, user.id, timedelta(minutes=20))

    return {'access_token': token, 'token_type': 'bearer'}


@auth.post('/refresh', response_model=Token)
async def refresh_access_token(current_user: Annotated[dict, Depends(get_current_user)]):
    # TODO: validate refresh token
    #  load expiry from config
    token = create_access_token(current_user['username'], current_user['id'], timedelta(minutes=20))
    return {'access_token': token, 'token_type': 'bearer'}


@auth.post('/logout')
async def logout():
    # TODO
    return {'message': 'logout endpoint - to be implemented'}
