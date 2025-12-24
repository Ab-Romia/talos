import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from sqlalchemy import create_engine, text
from modules.model.base import Base
from sqlalchemy.orm import Session

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    Base.metadata.create_all(engine)
    yield


app = FastAPI(title='Temp', lifespan=lifespan)

engine = create_engine(
    os.environ.get('DATABASE_URL'),
    echo=True,
    connect_args={}
)


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
