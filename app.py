from datetime import datetime, timedelta, timezone
import os
from contextlib import asynccontextmanager
from http.client import HTTPException
from typing import Annotated
from dotenv import load_dotenv
from fastapi import FastAPI, Depends ,HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from starlette import status
from modules.model.base import Base
from sqlalchemy.orm import Session, sessionmaker
from modules.app.auth  import hash_password,verify_password
from fastapi.security import OAuth2PasswordRequestForm ,OAuth2PasswordBearer #pass bearer token in header of endpoint
from modules.model.identity import User,UserPassword
from jose import jwt, JWTError

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    Base.metadata.create_all(engine)
    yield


app = FastAPI(title='Temp', lifespan=lifespan)
#for jwt signature
SECRET_KEY='123'
ALGORITHM='HS256'
oauth2_bearer=OAuth2PasswordBearer(tokenUrl='token') #url that client will send to applcation, verify token as dependency

engine = create_engine(
    os.environ.get('DATABASE_URL'),
    echo=True,
    connect_args={}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)



def get_db():
    db=SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session,Depends(get_db)]

def authenticate_user(username: str ,password:str , db):
    user = db.query(User).filter(User.username==username).first()
    if not user:
        return False
    user_password = db.query(UserPassword).filter(UserPassword.user_id == user.id).first()
    if not user_password:
        return False
    if not verify_password(password,user_password.hashed_password):
        return False
    return user

def create_access_token(username: str, user_id: int, expires_delta:timedelta):
    encode = {'sub':username , 'id': str(user_id)}
    expires = datetime.now(timezone.utc) + expires_delta
    encode.update({'exp': expires})
    return jwt.encode(encode,SECRET_KEY,algorithm=ALGORITHM)

#each operation that needs security we'll call this function to verify the token being passed in
async def get_current_user(token: Annotated[str, Depends(oauth2_bearer)]):
    try:
        payload=jwt.decode(token,SECRET_KEY,algorithms=[ALGORITHM])
        username: str = payload.get('sub')
        user_id: int = payload.get('id')
        if user_id in None or username is None:
            raise HTTPException(status_code= status.HTTP_401_UNAUTHORIZED, detail='could not validate user.')
        return {'username': username , 'id': user_id}
    except JWTError:
        raise HTTPException(status_code= status.HTTP_401_UNAUTHORIZED, detail='could not validate user.')


class CreateUserRequest(BaseModel):
    username: str
    primary_email: str
    email_verified: bool
    password: str
    name: str
    created_at: datetime = datetime.now(timezone.utc)
    data: str
    roles: str

class Token(BaseModel):
    access_token: str
    token_type: str


@app.post('/api',status_code=status.HTTP_201_CREATED)
async def CreateUser(db: db_dependency,
                     create_user: CreateUserRequest):
    create_user_model = User(
        username=create_user.username,
        primary_email=create_user.primary_email,
        email_verified=True,
        name=create_user.name,
        created_at=create_user.created_at,
        data=create_user.data,
        roles=[]

    )
    db.add(create_user_model)
    db.flush()
    create_password=UserPassword(
        user_id=create_user_model.id,
        hashed_password=hash_password(create_user.password),
        created_at=create_user.created_at

    )

    db.add(create_password)

    db.commit()

@app.post('/token',response_model=Token)
async def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm,Depends()],
                                 db: db_dependency ):
    user = authenticate_user(form_data.username,form_data.password,db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='could not validate user.')
        #return 'Failed Authentication'

    token = create_access_token(user.username,user.id,timedelta(minutes=20))
    
    return {'access_token': token , 'token_type': 'bearer'}


@app.get('/', response_class=HTMLResponse)
async def root():
    with open('templates/index.html', 'r') as f:
        return f.read()


@app.get('/smily', response_class=HTMLResponse)
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙂</p>')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app,
                host=os.environ.get('HOST'),
                port=int(os.environ.get('PORT'))
                )
