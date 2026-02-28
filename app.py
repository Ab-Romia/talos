import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from backend.app.auth import auth as auth_router
from backend.app.auth import get_current_user
from backend.model.base import Base, engine

load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    Base.metadata.create_all(engine)
    yield


app = FastAPI(title='Temp', lifespan=lifespan)

app.include_router(auth_router)


@app.get('/', response_class=HTMLResponse)
async def root():
    with open('frontend/templates/index.html', 'r') as f:
        return f.read()


@app.get('/smily', response_class=HTMLResponse)
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙂</p>')


@app.get('/smily-protected',
         response_class=HTMLResponse,
         dependencies=[Depends(get_current_user)])
async def smily():
    return HTMLResponse('<p style="font-size:24em";>🙃</p>')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app,
                host=os.environ.get('HOST'),
                port=int(os.environ.get('PORT'))
                )
