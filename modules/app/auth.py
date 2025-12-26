import os
from datetime import timedelta, datetime, timezone
from typing import Annotated

import bcrypt
import fastapi
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError

from pydantic import BaseModel
from starlette import status

from modules.model.identity import User, UserPassword
from modules.model.base import db_dependency

# TODO:
#  cookies,
#  refresh tokens,
#  sessions,
#  identity providers other than password
#  password reset,
#  logout,


auth = fastapi.APIRouter(prefix='/api/auth')

# TODO: move to config
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY').encode('utf-8')
JWT_ALGORITHM = 'HS256'
oauth2_bearer = OAuth2PasswordBearer(tokenUrl='/api/auth/token')


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


class CreateUserRequest(BaseModel):
    username: str
    primary_email: str
    password: str
    name: str


class Token(BaseModel):
    access_token: str
    token_type: str


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
