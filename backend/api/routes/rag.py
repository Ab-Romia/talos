"""RAG system routes."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.deps.database import get_db
from backend.api.deps.auth import get_current_user, get_current_user_optional
from backend.api.schemas.rag import (
    RAGQueryRequest,
    RAGQueryResponse,
    RAGConfigResponse,
    RAGHealthResponse,
    SourceDocument,
)
from backend.model.identity import User
from backend.services.rag_service import RAGService

router = APIRouter()


@router.post("/query", response_model=RAGQueryResponse)
async def query_rag(
    request: RAGQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RAGQueryResponse:
    """
    Execute a RAG query.

    Args:
        request: RAG query request
        current_user: Currently authenticated user
        db: Database session

    Returns:
        RAG query response with answer and sources
    """
    rag_service = RAGService()

    try:
        result = rag_service.query(
            query=request.query,
            workspace_id=str(request.workspace_id) if request.workspace_id else None,
            top_k=request.top_k,
            include_sources=request.include_sources,
            filters=request.filters,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"RAG query failed: {str(e)}",
        )

    # Convert sources
    sources = []
    for source in result.get("sources", []):
        sources.append(
            SourceDocument(
                content=source.get("content", ""),
                document_id=source.get("document_id"),
                document_name=source.get("document_name"),
                page=source.get("page"),
                chunk_index=source.get("chunk_index"),
                score=source.get("score"),
                metadata=source.get("metadata"),
            )
        )

    return RAGQueryResponse(
        answer=result["answer"],
        query=request.query,
        sources=sources,
        query_type=result.get("query_type"),
        processed_query=result.get("processed_query"),
        retrieval_latency_ms=result.get("retrieval_latency_ms"),
        generation_latency_ms=result.get("generation_latency_ms"),
        total_latency_ms=result.get("total_latency_ms"),
        metadata=result.get("metadata"),
    )


@router.get("/config", response_model=RAGConfigResponse)
async def get_rag_config(
    current_user: User = Depends(get_current_user),
) -> RAGConfigResponse:
    """
    Get RAG system configuration.

    Args:
        current_user: Currently authenticated user

    Returns:
        RAG configuration information
    """
    rag_service = RAGService()
    config = rag_service.get_config()

    return RAGConfigResponse(
        pipeline_type=config.get("pipeline_type", "modular"),
        embedding_model=config.get("embedding_model", "text-embedding-3-small"),
        llm_model=config.get("llm_model", "gpt-4o-mini"),
        retrieval_method=config.get("retrieval_method", "hybrid"),
        reranker_enabled=config.get("reranker_enabled", True),
        reranker_model=config.get("reranker_model"),
        query_processing_enabled=config.get("query_processing_enabled", True),
        routing_enabled=config.get("routing_enabled", True),
        compression_enabled=config.get("compression_enabled", False),
        memory_enabled=config.get("memory_enabled", True),
        collection_name=config.get("collection_name", "rag_collection"),
    )


@router.get("/health", response_model=RAGHealthResponse)
async def health_check(
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> RAGHealthResponse:
    """
    Check RAG system health.

    Args:
        current_user: Optional current user

    Returns:
        Health status
    """
    rag_service = RAGService()

    try:
        health = rag_service.health_check()
        return RAGHealthResponse(
            status="healthy" if health.get("healthy", False) else "unhealthy",
            vector_store_connected=health.get("vector_store_connected", False),
            llm_available=health.get("llm_available", False),
            embedding_service_available=health.get("embedding_service_available", False),
            indexed_documents=health.get("indexed_documents", 0),
            last_ingestion=health.get("last_ingestion"),
        )
    except Exception as e:
        return RAGHealthResponse(
            status="unhealthy",
            vector_store_connected=False,
            llm_available=False,
            embedding_service_available=False,
            indexed_documents=0,
            last_ingestion=None,
        )


@router.post("/clear-memory", status_code=status.HTTP_204_NO_CONTENT)
async def clear_conversation_memory(
    conversation_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Clear conversation memory.

    Args:
        conversation_id: Optional specific conversation to clear
        current_user: Currently authenticated user
    """
    rag_service = RAGService()
    rag_service.clear_memory(
        user_id=str(current_user.id),
        conversation_id=str(conversation_id) if conversation_id else None,
    )
