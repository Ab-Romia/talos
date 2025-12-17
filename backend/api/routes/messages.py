"""Message routes with RAG integration."""

import asyncio
from datetime import datetime
from typing import List, Optional, AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.api.deps.database import get_db
from backend.api.deps.auth import get_current_user
from backend.api.schemas.message import (
    MessageCreate,
    MessageResponse,
    MessageRole,
    ChatRequest,
    ChatResponse,
    ChatStreamResponse,
    SourceInfo,
    MessageListResponse,
)
from backend.model.identity import User
from backend.model.messaging import Workspace, Chatroom, Message
from backend.services.rag_service import RAGService

router = APIRouter()


@router.get("", response_model=MessageListResponse)
async def list_messages(
    chatroom_id: UUID,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageListResponse:
    """
    List messages in a chatroom.

    Args:
        chatroom_id: Chatroom ID
        limit: Maximum number of messages to return
        offset: Number of messages to skip
        current_user: Currently authenticated user
        db: Database session

    Returns:
        List of messages
    """
    # Verify chatroom access
    chatroom = db.execute(
        select(Chatroom).where(
            Chatroom.id == chatroom_id,
            Chatroom.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not chatroom:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    # Verify workspace access
    workspace = db.execute(
        select(Workspace).where(
            Workspace.id == chatroom.workspace_id,
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    # Get total count
    total = db.execute(
        select(func.count(Message.id)).where(
            Message.chatroom_id == chatroom_id,
        )
    ).scalar() or 0

    # Get messages
    messages = db.execute(
        select(Message)
        .where(Message.chatroom_id == chatroom_id)
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).scalars().all()

    # Get sender names
    message_responses = []
    for message in reversed(messages):  # Reverse to get chronological order
        sender_name = None
        role = MessageRole.USER
        if message.sender_id:
            sender = db.execute(
                select(User).where(User.id == message.sender_id)
            ).scalar_one_or_none()
            if sender:
                sender_name = sender.name or sender.username
        else:
            role = MessageRole.ASSISTANT
            sender_name = "AI Assistant"

        message_responses.append(
            MessageResponse(
                id=message.id,
                content=message.content,
                sender_id=message.sender_id,
                sender_name=sender_name,
                chatroom_id=message.chatroom_id,
                workspace_id=message.workspace_id,
                role=role,
                created_at=message.created_at,
            )
        )

    return MessageListResponse(
        messages=message_responses,
        total=total,
        has_more=(offset + limit) < total,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    chat_request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    """
    Send a chat message and get AI response.

    This endpoint:
    1. Saves the user message
    2. Processes through RAG pipeline
    3. Saves the AI response
    4. Returns the response with sources

    Args:
        chat_request: Chat request with message
        current_user: Currently authenticated user
        db: Database session

    Returns:
        Chat response with AI answer and sources
    """
    import time
    start_time = time.perf_counter()

    # Verify chatroom access
    chatroom = db.execute(
        select(Chatroom).where(
            Chatroom.id == chat_request.chatroom_id,
            Chatroom.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not chatroom:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    # Verify workspace access
    workspace = db.execute(
        select(Workspace).where(
            Workspace.id == chatroom.workspace_id,
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    # Save user message
    user_message = Message(
        content=chat_request.message,
        sender_id=current_user.id,
        chatroom_id=chat_request.chatroom_id,
        workspace_id=chatroom.workspace_id,
    )
    db.add(user_message)
    db.flush()

    # Get conversation history for context
    recent_messages = db.execute(
        select(Message)
        .where(Message.chatroom_id == chat_request.chatroom_id)
        .order_by(Message.created_at.desc())
        .limit(10)
    ).scalars().all()

    conversation_history = []
    for msg in reversed(recent_messages):
        role = "user" if msg.sender_id else "assistant"
        conversation_history.append({"role": role, "content": msg.content})

    # Process through RAG pipeline
    rag_service = RAGService()
    try:
        rag_result = rag_service.query(
            query=chat_request.message,
            workspace_id=str(workspace.id),
            conversation_history=conversation_history,
            include_sources=chat_request.include_sources,
        )
    except Exception as e:
        # Fallback response on RAG error
        rag_result = {
            "answer": "I apologize, but I'm having trouble processing your request right now. Please try again.",
            "sources": [],
            "query_type": "error",
        }

    # Save AI response
    ai_message = Message(
        content=rag_result["answer"],
        sender_id=None,  # AI has no sender_id
        chatroom_id=chat_request.chatroom_id,
        workspace_id=chatroom.workspace_id,
    )
    db.add(ai_message)
    db.commit()
    db.refresh(ai_message)

    # Calculate processing time
    processing_time_ms = (time.perf_counter() - start_time) * 1000

    # Build response
    sources = []
    for source in rag_result.get("sources", []):
        sources.append(
            SourceInfo(
                content=source.get("content", ""),
                document_name=source.get("document_name"),
                page=source.get("page"),
                score=source.get("score"),
                metadata=source.get("metadata"),
            )
        )

    return ChatResponse(
        message=MessageResponse(
            id=ai_message.id,
            content=ai_message.content,
            sender_id=None,
            sender_name="AI Assistant",
            chatroom_id=ai_message.chatroom_id,
            workspace_id=ai_message.workspace_id,
            role=MessageRole.ASSISTANT,
            created_at=ai_message.created_at,
            sources=[s.model_dump() for s in sources] if sources else None,
        ),
        sources=sources,
        query_type=rag_result.get("query_type"),
        processing_time_ms=processing_time_ms,
    )


@router.post("/chat/stream")
async def chat_stream(
    chat_request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Send a chat message and get streaming AI response.

    Args:
        chat_request: Chat request with message
        current_user: Currently authenticated user
        db: Database session

    Returns:
        Streaming response with AI answer chunks
    """
    # Verify access (same as non-streaming endpoint)
    chatroom = db.execute(
        select(Chatroom).where(
            Chatroom.id == chat_request.chatroom_id,
            Chatroom.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not chatroom:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    workspace = db.execute(
        select(Workspace).where(
            Workspace.id == chatroom.workspace_id,
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatroom not found",
        )

    async def generate_response() -> AsyncGenerator[str, None]:
        """Generate streaming response."""
        import json

        # Save user message
        user_message = Message(
            content=chat_request.message,
            sender_id=current_user.id,
            chatroom_id=chat_request.chatroom_id,
            workspace_id=chatroom.workspace_id,
        )
        db.add(user_message)
        db.flush()

        # Get RAG service and stream response
        rag_service = RAGService()
        full_response = ""

        try:
            async for chunk in rag_service.query_stream(
                query=chat_request.message,
                workspace_id=str(workspace.id),
            ):
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk, 'done': False})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'content': 'Error processing request', 'done': True})}\n\n"
            return

        # Save AI response
        ai_message = Message(
            content=full_response,
            sender_id=None,
            chatroom_id=chat_request.chatroom_id,
            workspace_id=chatroom.workspace_id,
        )
        db.add(ai_message)
        db.commit()

        # Send final message with message ID
        yield f"data: {json.dumps({'content': '', 'done': True, 'message_id': str(ai_message.id)})}\n\n"

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
    )


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    message_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a message.

    Args:
        message_id: Message ID
        current_user: Currently authenticated user
        db: Database session
    """
    message = db.execute(
        select(Message).where(Message.id == message_id)
    ).scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    # Verify workspace access
    workspace = db.execute(
        select(Workspace).where(
            Workspace.id == message.workspace_id,
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    # Only allow deleting own messages or if workspace owner
    if message.sender_id != current_user.id and workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete this message",
        )

    db.delete(message)
    db.commit()
