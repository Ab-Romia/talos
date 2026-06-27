"""Document processing pipeline: extract text, chunk, and prepare for RAG ingestion."""

import os
import tempfile

from fsspec.asyn import AsyncFileSystem
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from config import global_rag_config
from files.model import File
from utils.logger import get_logger

logger = get_logger(__name__)


# TODO: update storage interface
async def process_document(file_record: File, db: Session, storage: AsyncFileSystem):
    """Download the file from MinIO, extract text, chunk, and ingest into Milvus."""
    ext = os.path.splitext(file_record.filename)[1].lower()

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Download from MinIO
        await storage.download_file_to_path(file_record.id.hex, tmp_path)
        logger.info("Downloaded file for processing", file_id=str(file_record.id), path=tmp_path)

        # Extract text elements
        elements = _extract_text(tmp_path, file_record.content_type)

        # Build LangChain documents with metadata
        docs = [
            Document(
                page_content=el_text,
                metadata={
                    "workspace_id": str(file_record.workspace_id),
                    "file_id": str(file_record.id),
                    "filename": file_record.filename,
                    "page_number": el_meta.get("page_number", 0),
                },
            )
            for el_text, el_meta in elements
            if el_text and el_text.strip()
        ]

        if not docs:
            logger.warning("No text extracted from document", file_id=str(file_record.id))
            file_record.chunk_count = 0
            db.commit()
            return

        # Chunk
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=global_rag_config.chunk_size,
            chunk_overlap=global_rag_config.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        chunks = splitter.split_documents(docs)

        # Add chunk index to metadata
        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = i

        # Clear any chunks from prior attempts so retries stay idempotent.
        # Milvus has no unique constraint on (file_id, chunk_index), so
        # re-ingesting without this would duplicate chunks.
        from rag.vector_store import delete_file_chunks
        delete_file_chunks(
            str(file_record.id),
            workspace_id=str(file_record.workspace_id),
        )

        from rag.ingestion import ingest_file_chunks
        ingest_file_chunks(chunks, str(file_record.workspace_id), str(file_record.id))

        file_record.chunk_count = len(chunks)
        db.commit()

        logger.info(
            "Document chunked and ingested",
            file_id=str(file_record.id),
            num_chunks=len(chunks),
            num_raw_elements=len(docs),
        )

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _extract_text(file_path: str, content_type: str) -> list[tuple[str, dict]]:
    """Extract text from a file. Returns a list of (text, metadata) tuples.

    Tries unstructured first, falls back to plain text reading for txt/md.
    """
    try:
        from unstructured.partition.auto import partition
        elements = partition(filename=file_path, strategy="fast")
        return [
            (
                el.text,
                {
                    "page_number": getattr(el.metadata, "page_number", 0) if hasattr(el, "metadata") else 0,
                },
            )
            for el in elements
            if hasattr(el, "text") and el.text
        ]
    except ImportError:
        logger.warning("unstructured not installed, using fallback text extraction")
        return _fallback_extract(file_path, content_type)


def _fallback_extract(file_path: str, content_type: str) -> list[tuple[str, dict]]:
    """Fallback text extraction for when unstructured is not available."""
    if content_type in ("text/plain", "text/markdown"):
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        return [(text, {"page_number": 0})]

    logger.warning(
        "Cannot extract text without unstructured library",
        content_type=content_type,
        file_path=file_path,
    )
    return []
