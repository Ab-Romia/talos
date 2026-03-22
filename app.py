from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from backend.auth import auth_router, active_user
from backend.auth.helpers import UserDep
from backend.auth.session import session_middleware
from config import cfg
from model import Base
from model import engine

templates = Jinja2Templates(directory="frontend/templates")


@asynccontextmanager
async def lifespan(_: FastAPI):
    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    Base.metadata.create_all(engine)
    yield


app = FastAPI(title='Temp', lifespan=lifespan)
app.include_router(auth_router, prefix="/api/auth")
app.add_middleware(SessionMiddleware, secret_key=cfg().auth.jwe_secret)
app.middleware("http")(session_middleware)


@app.get('/', response_class=HTMLResponse)
async def root():
    with open('frontend/templates/pages/home.html', 'r') as f:
        return f.read()


@app.get('/config')
async def config_page():
    return cfg()


@app.get('/passkey-test', response_class=HTMLResponse)
async def passkey_test_page(request: Request, user: UserDep):
    return templates.TemplateResponse(request, "pages/passkey_test.html", {"username": user.username})


@app.get('/smily')
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙂</p>')


@app.get('/smily-protected', dependencies=[Depends(active_user)])
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙃</p>')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=cfg().app_host, port=cfg().app_port)
