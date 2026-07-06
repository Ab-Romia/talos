"""Document processing pipeline: extract text, chunk, and prepare for RAG ingestion."""

import os
import tempfile

from fsspec.asyn import AsyncFileSystem
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from config import global_rag_config
from filesystem.model import File
from utils.logger import get_logger

logger = get_logger(__name__)

# Element categories that are retrieval noise: running headers/footers, page
# breaks, images. Dropped ONLY on the "by_title" path so "recursive" stays a
# faithful reproduction of the legacy corpus for the ablation baseline.
_NOISE_CATEGORIES = {"Header", "Footer", "PageBreak", "Image"}


def _partition_elements(file_path: str) -> list:
    """Partition a file into unstructured elements. Raises ImportError when
    unstructured is unavailable (caller falls back to plain-text extraction)."""
    from unstructured.partition.auto import partition
    return partition(filename=file_path, strategy="fast")


def _section_title_of(chunk) -> str | None:
    for el in getattr(chunk.metadata, "orig_elements", None) or []:
        if el.category == "Title" and (el.text or "").strip():
            return el.text.strip()
    return None


def build_chunk_documents(elements: list, *, base_metadata: dict, config=None) -> list[Document]:
    """Single chunking entrypoint: unstructured elements -> retrieval-ready Documents.

    strategy "recursive" (legacy): one Document per element, RecursiveCharacterTextSplitter
    splits oversized ones — it never merges, so short elements stay fragments.
    strategy "by_title": noise elements dropped, sections packed/merged by
    chunk_by_title, section title carried in metadata (optionally prepended).
    """
    cfg = config if config is not None else global_rag_config

    if cfg.chunking_strategy == "by_title":
        from unstructured.chunking.title import chunk_by_title
        kept = [
            el for el in elements
            if el.category not in _NOISE_CATEGORIES and (getattr(el, "text", "") or "").strip()
        ]
        chunks = chunk_by_title(
            kept,
            max_characters=cfg.chunk_size,
            new_after_n_chars=min(800, cfg.chunk_size),
            combine_text_under_n_chars=200,
            multipage_sections=True,
            include_orig_elements=True,
        )
        docs = []
        for chunk in chunks:
            section = _section_title_of(chunk)
            text = chunk.text
            if cfg.chunk_prepend_section_title and section:
                text = f"[{section}]\n{text}"
            docs.append(Document(
                page_content=text,
                metadata={
                    **base_metadata,
                    "page_number": getattr(chunk.metadata, "page_number", 0) or 0,
                    "section": section or "",
                },
            ))
        return docs

    # legacy path — must reproduce the pre-2026-07 corpus exactly
    docs = [
        Document(
            page_content=el.text,
            metadata={
                **base_metadata,
                "page_number": (getattr(el.metadata, "page_number", 0) or 0) if hasattr(el, "metadata") else 0,
            },
        )
        for el in elements
        if getattr(el, "text", None) and el.text.strip()
    ]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=cfg.chunk_size,
        chunk_overlap=cfg.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(docs)


# TODO: update storage interface
async def process_document(file_record: File, db: Session, storage: AsyncFileSystem):
    """Download the file from MinIO, extract text, chunk, and ingest into Milvus.

    NOTE: `storage` is currently UNUSED on this path — the workspace-scoped
    MinIOFileSystem cannot address real uploaded object keys (its split_path
    inserts a channel segment the keys don't contain), so the download below
    builds an unscoped client from app config. The parameter is kept because
    tasks.py constructs it for the image path and signature parity matters
    until the storage interface TODO above is resolved.
    """
    ext = os.path.splitext(file_record.filename)[1].lower()

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Download from MinIO. File.uri is "minio://<relative-path>"; strip the
        # protocol only — the workspace-scoped MinIOFileSystem.split_path adds
        # bucket/workspace/channel. (download_file_to_path was a dead API.)
        # The stored uri is the EXACT object key (bucket/ws/files/<id>/<name>).
        # The workspace-scoped MinIOFileSystem cannot address it: its split_path
        # always inserts a channel segment (ws/{ch or '.'}) that real uploaded
        # keys don't contain, so scoped downloads 404/XMinioInvalidResourceName.
        # Download by exact key with an unscoped client built from app config.
        object_key = str(file_record.uri).removeprefix("minio://")
        from s3fs import S3FileSystem
        from config import cfg
        _m = cfg().minio
        raw_fs = S3FileSystem(
            key=_m.access_key,
            secret=_m.secret_key.get_secret_value(),
            endpoint_url=_m.internal_endpoint,
            use_ssl=_m.secure,
            asynchronous=True,
            # fsspec caches instances by params; a cached client is bound to a
            # previous (possibly closed) event loop when callers use asyncio.run
            # per file (the re-ingest script does). Always build loop-fresh.
            skip_instance_cache=True,
        )
        await raw_fs._get_file(object_key, tmp_path)
        logger.info("Downloaded file for processing", file_id=str(file_record.id), path=tmp_path)

        base_metadata = {
            "workspace_id": str(file_record.workspace_id),
            "file_id": str(file_record.id),
            "filename": file_record.filename,
        }
        try:
            elements = _partition_elements(tmp_path)
            chunks = build_chunk_documents(elements, base_metadata=base_metadata)
        except ImportError:
            logger.warning("unstructured not installed, using fallback text extraction")
            docs = [
                Document(page_content=text, metadata={**base_metadata, "page_number": meta.get("page_number", 0)})
                for text, meta in _fallback_extract(tmp_path, file_record.content_type)
                if text and text.strip()
            ]
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=global_rag_config.chunk_size,
                chunk_overlap=global_rag_config.chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
            )
            chunks = splitter.split_documents(docs)

        if not chunks:
            logger.warning("No text extracted from document", file_id=str(file_record.id))
            file_record.chunk_count = 0
            db.commit()
            return

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
        )

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


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
