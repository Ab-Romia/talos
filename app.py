from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import auth_router, active_user
from backend.auth.utils.session import SessionMiddleware
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
app.add_middleware(SessionMiddleware)


@app.get('/', response_class=HTMLResponse)
async def root():
    with open('frontend/templates/pages/home.html', 'r') as f:
        return f.read()


@app.get("/signup", response_class=HTMLResponse)
def signup_page():
    # TODO:
    return HTMLResponse("TODO")


@app.get("/signup/verify")
def complete_signup(token: str):
    # TODO:
    return HTMLResponse(f"TODO: Token: {token}")


@app.get('/smiley')
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙂</p>')


@app.get('/smiley-protected', dependencies=[Depends(active_user)])
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙃</p>')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=cfg().app_host, port=cfg().app_port)
