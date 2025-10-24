import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

load_dotenv()
app = FastAPI(title='Temp')


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
