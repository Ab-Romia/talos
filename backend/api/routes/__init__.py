"""API routes package."""

from fastapi import APIRouter

from backend.api.routes import auth, workspaces, chatrooms, messages, documents, rag

api_router = APIRouter()

# Include all route modules
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["Workspaces"])
api_router.include_router(chatrooms.router, prefix="/chatrooms", tags=["Chatrooms"])
api_router.include_router(messages.router, prefix="/messages", tags=["Messages"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])
api_router.include_router(rag.router, prefix="/rag", tags=["RAG"])
