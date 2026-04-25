"""Document processing pipeline: extract text, chunk, and prepare for RAG ingestion."""

import os
import tempfile

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from config import global_rag_config
from files.model import FileAttachment
from config import get_effective_rag_config
from files.storage import MinIOStorage
from utils.logger import get_logger

logger = get_logger(__name__)

NO_TEXT_EXTRACTED = (
    "No extractable text from this file. If you can read text in a PDF viewer, it may be "
    "scanned images (needs OCR) or an unusual font/encoding: try re-exporting as PDF from "
    "your editor or printing to PDF, then re-upload."
)


async def process_document(
        file_record: FileAttachment,
        db: Session,
        storage: MinIOStorage,
):
    """Download file from MinIO, extract text, chunk, and ingest into Milvus."""
    ext = os.path.splitext(file_record.original_filename)[1].lower()

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
                    "filename": file_record.original_filename,
                    "page_number": el_meta.get("page_number", 0),
                },
            )
            for el_text, el_meta in elements
            if el_text and el_text.strip()
        ]

        if not docs:
            logger.warning("No text extracted from document", file_id=str(file_record.id))
            raise ValueError(NO_TEXT_EXTRACTED)

        # Chunk
        rc = get_effective_rag_config()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=rc.chunk_size,
            chunk_overlap=rc.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        chunks = splitter.split_documents(docs)
        if not chunks:
            logger.warning("Chunking produced no segments", file_id=str(file_record.id))
            raise ValueError(NO_TEXT_EXTRACTED)

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


def _elements_to_tuples(elements) -> list[tuple[str, dict]]:
    return [
        (
            el.text,
            {
                "page_number": (
                    getattr(el.metadata, "page_number", 0) if hasattr(el, "metadata") else 0
                ),
            },
        )
        for el in elements
        if hasattr(el, "text") and el.text
    ]


def _extract_pdf_unstructured(file_path: str) -> list[tuple[str, dict]]:
    """Unstructured library: try several strategies; many PDFs need more than ``fast``."""
    try:
        from unstructured.partition.auto import partition
    except ImportError:
        return []
    for strategy in ("fast", "hi_res", "auto"):
        try:
            elements = partition(filename=file_path, strategy=strategy)
            out = _elements_to_tuples(elements)
            if out:
                if strategy != "fast":
                    logger.info("PDF text via unstructured", strategy=strategy, path=file_path)
                return out
        except Exception:
            logger.debug("unstructured PDF strategy failed", strategy=strategy, exc_info=True)
    return []


def _extract_pdf_pypdf(file_path: str) -> list[tuple[str, dict]]:
    """Lightweight text layer extraction; works when unstructured misses embedded text."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    out: list[tuple[str, dict]] = []
    try:
        reader = PdfReader(file_path)
        for i, page in enumerate(reader.pages):
            raw = page.extract_text() or ""
            if raw.strip():
                out.append((raw, {"page_number": i + 1}))
    except Exception:
        logger.warning("pypdf fallback failed for PDF", path=file_path, exc_info=True)
    return out


def _extract_pdf_pymupdf(file_path: str) -> list[tuple[str, dict]]:
    """PyMuPDF often extracts text that pypdf/unstructured miss (fonts, encodings)."""
    try:
        import fitz
    except ImportError:
        return []
    out: list[tuple[str, dict]] = []
    try:
        doc = fitz.open(file_path)
        try:
            for i in range(len(doc)):
                raw = doc[i].get_text() or ""
                if raw.strip():
                    out.append((raw, {"page_number": i + 1}))
        finally:
            doc.close()
    except Exception:
        logger.warning("PyMuPDF fallback failed for PDF", path=file_path, exc_info=True)
    return out


def _extract_pdf(file_path: str) -> list[tuple[str, dict]]:
    """PDFs: unstructured → pypdf → PyMuPDF so real text layers are not missed."""
    for name, fn in (
        ("unstructured", _extract_pdf_unstructured),
        ("pypdf", _extract_pdf_pypdf),
        ("pymupdf", _extract_pdf_pymupdf),
    ):
        out = fn(file_path)
        if out:
            if name != "unstructured":
                logger.info("PDF text extracted with fallback", engine=name, path=file_path)
            return out
    return []


def _extract_text(file_path: str, content_type: str) -> list[tuple[str, dict]]:
    """Extract text from a file. Returns list of (text, metadata) tuples.

    PDFs use multiple engines; other types use unstructured or simple read for txt/md.
    """
    if content_type == "application/pdf":
        return _extract_pdf(file_path)

    try:
        from unstructured.partition.auto import partition

        elements = partition(filename=file_path, strategy="fast")
        out = _elements_to_tuples(elements)
        if not out and content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            try:
                elements = partition(filename=file_path, strategy="hi_res")
                out = _elements_to_tuples(elements)
            except Exception:
                logger.debug("DOCX hi_res failed", exc_info=True)
        return out
    except ImportError:
        logger.warning("unstructured not installed, using fallback text extraction")
        return _fallback_extract(file_path, content_type)
    except Exception:
        logger.warning("unstructured partition failed, trying text fallbacks", exc_info=True)
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
