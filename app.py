import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import auth_router, active_user
from backend.auth.common import SessionCookieToHeaderMiddleware
from model.base import engine, Base
from model.config import get_config

load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    Base.metadata.create_all(engine)
    yield


app = FastAPI(title='Temp', lifespan=lifespan)
app.include_router(auth_router, prefix="/auth")
app.add_middleware(SessionCookieToHeaderMiddleware)


@app.get('/')
async def root():
    with open('frontend/templates/pages/home.html', 'r') as f:
        return f.read()


@app.get('/config')
async def config():
    config = get_config()
    return config


@app.get('/smily')
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙂</p>')


@app.get('/smily-protected', dependencies=[Depends(active_user)])
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙃</p>')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app,
                host=os.environ.get('HOST'),
                port=int(os.environ.get('PORT'))
                )
