import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlmodel import create_engine, SQLModel

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import modules.model  # noqa: F401

    SQLModel.metadata.create_all(engine)
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


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app,
                host=os.environ.get('HOST'),
                port=int(os.environ.get('PORT'))
                )
