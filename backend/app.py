"""
Talos - AI-Powered Collaborative RAG System

Main FastAPI application entry point.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.model.base import Base
from backend.api.routes import api_router

# Load environment variables
load_dotenv()

# Database configuration
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://talos_app:password@localhost:5432/talos"
)

engine = create_engine(
    DATABASE_URL,
    echo=os.environ.get("DB_ECHO", "false").lower() == "true",
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown tasks.
    """
    # Startup
    import backend.model  # noqa: F401 - Import models for SQLAlchemy

    # Create PostgreSQL extensions
    with Session(engine) as session:
        try:
            session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
            session.commit()
        except Exception as e:
            print(f"Warning: Could not create citext extension: {e}")

    # Create all tables
    Base.metadata.create_all(engine)

    print("Talos API started successfully")

    yield

    # Shutdown
    print("Talos API shutting down")


# Create FastAPI application
app = FastAPI(
    title="Talos",
    description="AI-Powered Collaborative RAG System",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Configure CORS
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api")


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """Check if the API is running."""
    return {"status": "healthy", "service": "talos-api"}


# Root endpoint
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    """Serve landing page or redirect to docs."""
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Talos API</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #24273a 0%, #363a4f 100%);
                color: #cad3f5;
            }
            .container {
                text-align: center;
                padding: 40px;
            }
            h1 {
                font-size: 3em;
                margin-bottom: 10px;
                color: #c6a0f6;
            }
            p {
                font-size: 1.2em;
                margin-bottom: 30px;
                color: #a5adcb;
            }
            .links a {
                display: inline-block;
                padding: 12px 24px;
                margin: 0 10px;
                background: #c6a0f6;
                color: #24273a;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                transition: transform 0.2s, box-shadow 0.2s;
            }
            .links a:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(198, 160, 246, 0.3);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Talos API</h1>
            <p>AI-Powered Collaborative RAG System</p>
            <div class="links">
                <a href="/api/docs">API Documentation</a>
                <a href="/api/redoc">ReDoc</a>
                <a href="/health">Health Check</a>
            </div>
        </div>
    </body>
    </html>
    """)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal error occurred",
            "type": type(exc).__name__,
        },
    )


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    uvicorn.run(
        "backend.app:app",
        host=host,
        port=port,
        reload=os.environ.get("RELOAD", "true").lower() == "true",
    )
