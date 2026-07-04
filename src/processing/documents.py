"""Document processing pipeline: extract text, chunk, and prepare for RAG ingestion."""

import asyncio
import os
import tempfile

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from config import global_rag_config
from filesystem.model import File
from utils.logger import get_logger

logger = get_logger(__name__)


# TODO: update storage interface
async def process_document(file_record: File, db: Session, storage):
    """Download the file from MinIO, extract text, chunk, and ingest into Milvus."""
    ext = os.path.splitext(file_record.filename)[1].lower()

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if file_record.uri.startswith("gdrive://"):
            data = await _download_gdrive(file_record, db)
        else:
            key = file_record.uri.removeprefix("minio://")
            data = await asyncio.to_thread(storage.cat_file, key)
        with open(tmp_path, "wb") as f:
            f.write(data)
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
            raise ValueError(
                f"No extractable text found in '{file_record.filename}' "
                f"(content_type={file_record.content_type}). The file may be empty, "
                f"image-only/scanned, or an unsupported format."
            )

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


async def _download_gdrive(file_record: File, db: Session) -> bytes:
    from filesystem.gdrive import google_token_for, make_gdrive_fs, download_drive_bytes

    token = google_token_for(db, file_record.uploader_id)
    if token is None:
        raise ValueError("No connected Google Drive account for the uploader of this file")

    fs = await make_gdrive_fs(db, token)
    drive_id = file_record.uri.removeprefix("gdrive://").removeprefix("id:")
    return await download_drive_bytes(fs, drive_id)


def _extract_text(file_path: str, content_type: str) -> list[tuple[str, dict]]:
    ext = os.path.splitext(file_path)[1].lower()

    if content_type == "application/pdf" or ext == ".pdf":
        return _extract_pdf(file_path)

    if (
        content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or ext == ".docx"
    ):
        return _extract_docx(file_path)

    return _extract_plaintext(file_path)


def _extract_pdf(file_path: str) -> list[tuple[str, dict]]:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer

    results: list[tuple[str, dict]] = []
    for page_number, layout in enumerate(extract_pages(file_path), start=1):
        parts = [el.get_text() for el in layout if isinstance(el, LTTextContainer)]
        text = "".join(parts).strip()
        if text:
            results.append((text, {"page_number": page_number}))
    return results


def _extract_docx(file_path: str) -> list[tuple[str, dict]]:
    import html
    import re
    import zipfile

    with zipfile.ZipFile(file_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="replace")

    xml = re.sub(r"</w:p>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return [(text, {"page_number": 0})] if text else []


def _extract_plaintext(file_path: str) -> list[tuple[str, dict]]:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    return [(text, {"page_number": 0})] if text.strip() else []
