"""Document management routes."""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.api.deps.database import get_db
from backend.api.deps.auth import get_current_user
from backend.api.schemas.document import (
    DocumentCreate,
    DocumentResponse,
    DocumentUploadResponse,
    DocumentStatus,
    IngestionStatus,
    DocumentListResponse,
)
from backend.model.identity import User
from backend.model.messaging import Workspace
from backend.services.rag_service import RAGService

router = APIRouter()

# Supported file types
SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".md", ".json", ".csv"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# Upload directory
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "data/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# In-memory document storage (in production, use a database table)
_documents: dict = {}


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    workspace_id: UUID = Form(...),
    description: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Upload a document for RAG ingestion.

    Args:
        file: Document file to upload
        workspace_id: Workspace to associate document with
        description: Optional document description
        current_user: Currently authenticated user
        db: Database session

    Returns:
        Upload confirmation with document info
    """
    # Verify workspace access
    workspace = db.execute(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    # Validate file extension
    file_ext = Path(file.filename).suffix.lower() if file.filename else ""
    if file_ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Supported types: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )

    # Save file
    document_id = uuid.uuid4()
    file_path = UPLOAD_DIR / str(workspace_id) / f"{document_id}{file_ext}"
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "wb") as f:
        f.write(content)

    # Create document record
    document = DocumentResponse(
        id=document_id,
        name=file.filename or "Untitled",
        workspace_id=workspace_id,
        owner_id=current_user.id,
        description=description,
        file_type=file_ext,
        file_size=file_size,
        status=DocumentStatus.PENDING,
        chunk_count=0,
        created_at=datetime.now(),
        processed_at=None,
        metadata={"original_filename": file.filename},
    )

    # Store document (in production, save to database)
    _documents[str(document_id)] = {
        "document": document,
        "file_path": str(file_path),
    }

    # Start async ingestion (in production, use background task)
    try:
        rag_service = RAGService()
        ingestion_result = rag_service.ingest_file(
            file_path=str(file_path),
            document_id=str(document_id),
            workspace_id=str(workspace_id),
            metadata={
                "owner_id": str(current_user.id),
                "document_name": file.filename,
                "description": description,
            },
        )

        # Update document status
        document.status = DocumentStatus.COMPLETED
        document.chunk_count = ingestion_result.get("chunk_count", 0)
        document.processed_at = datetime.now()
        _documents[str(document_id)]["document"] = document

    except Exception as e:
        document.status = DocumentStatus.FAILED
        document.metadata["error"] = str(e)
        _documents[str(document_id)]["document"] = document

    return DocumentUploadResponse(
        document=document,
        message=f"Document uploaded and {'processed' if document.status == DocumentStatus.COMPLETED else 'queued for processing'}",
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    workspace_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    """
    List documents.

    Args:
        workspace_id: Optional workspace filter
        current_user: Currently authenticated user
        db: Database session

    Returns:
        List of documents
    """
    documents = []
    for doc_data in _documents.values():
        doc = doc_data["document"]
        if doc.owner_id == current_user.id:
            if workspace_id is None or doc.workspace_id == workspace_id:
                documents.append(doc)

    return DocumentListResponse(
        documents=documents,
        total=len(documents),
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """
    Get a specific document.

    Args:
        document_id: Document ID
        current_user: Currently authenticated user
        db: Database session

    Returns:
        Document details
    """
    doc_data = _documents.get(str(document_id))
    if not doc_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    doc = doc_data["document"]
    if doc.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return doc


@router.get("/{document_id}/status", response_model=IngestionStatus)
async def get_document_status(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IngestionStatus:
    """
    Get document ingestion status.

    Args:
        document_id: Document ID
        current_user: Currently authenticated user
        db: Database session

    Returns:
        Ingestion status
    """
    doc_data = _documents.get(str(document_id))
    if not doc_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    doc = doc_data["document"]
    if doc.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    progress = 100.0 if doc.status == DocumentStatus.COMPLETED else 0.0
    if doc.status == DocumentStatus.PROCESSING:
        progress = 50.0

    return IngestionStatus(
        document_id=document_id,
        status=doc.status,
        progress=progress,
        chunks_processed=doc.chunk_count if doc.status == DocumentStatus.COMPLETED else 0,
        total_chunks=doc.chunk_count,
        error_message=doc.metadata.get("error") if doc.status == DocumentStatus.FAILED else None,
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a document.

    Args:
        document_id: Document ID
        current_user: Currently authenticated user
        db: Database session
    """
    doc_data = _documents.get(str(document_id))
    if not doc_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    doc = doc_data["document"]
    if doc.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Delete file
    file_path = Path(doc_data["file_path"])
    if file_path.exists():
        file_path.unlink()

    # Remove from vector store
    try:
        rag_service = RAGService()
        rag_service.delete_document(str(document_id))
    except Exception:
        pass  # Ignore errors when deleting from vector store

    # Remove from storage
    del _documents[str(document_id)]
